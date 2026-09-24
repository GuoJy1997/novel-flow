"""持久化多章生产任务。读取不写状态；只有显式执行回执才产生成功记录。

CLI 示例：production.py status --project PATH --workflow production.yaml
宿主先 prompt，再 start 取得 attempt，执行后 finish --attempt TOKEN --exit-code N。
人工归档必须 accept --confirm；run 只执行固定模板的 command 节点。
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

import yaml
import pipeline
import subagent_registry as registry


class ProductionError(ValueError):
    pass


class RevisionConflict(ProductionError):
    pass


def digest(value):
    return 'sha256:' + hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                               separators=(',', ':')).encode('utf-8')).hexdigest()


def safe_path(root, value):
    if not isinstance(value, str) or not value or '\x00' in value:
        raise ProductionError('路径必须是非空字符串')
    value = value.replace('\\', '/')
    if value.startswith('/') or ':' in value or '..' in value.split('/'):
        raise ProductionError(f'路径必须在项目内: {value}')
    root = Path(root).resolve()
    path = root / value
    try:
        path.resolve().relative_to(root)
        # 目录递归哈希也不得跟随链接读取项目外文件。
        if path.is_dir():
            for item in path.rglob('*'):
                item.resolve().relative_to(root)
    except (ValueError, RuntimeError) as exc:
        raise ProductionError(f'路径越出项目: {value}') from exc
    return path


def workflow_path(root, workflow):
    if not isinstance(workflow, str) or '/' in workflow or '\\' in workflow or Path(workflow).suffix not in ('.yaml', '.yml'):
        raise ProductionError('生产清单必须是项目根目录 YAML 文件')
    return safe_path(root, workflow)


def chapter_graph(doc, chapter_id):
    import chapter_templates
    chapters = doc['chapters']
    index = next((i for i, c in enumerate(chapters) if c['id'] == chapter_id), None)
    if index is None:
        raise ProductionError(f'任务不包含章节实例: {chapter_id}')
    chapter = chapters[index]
    graph = chapter_templates.instantiate(doc['template']['id'], chapter['params'],
                                         chapter.get('overrides'), doc['template']['snapshot'])
    if index:
        previous = chapters[index - 1]
        previous_graph = chapter_templates.instantiate(doc['template']['id'], previous['params'],
                                                       previous.get('overrides'), doc['template']['snapshot'])
        previous_output = previous_graph['params']['chapter_output']
        inputs = graph['nodes']['explore_context'].setdefault('inputs', [])
        if previous_output not in inputs:
            inputs.append(previous_output)
    try:
        return pipeline.load_graph(yaml.safe_dump(graph, allow_unicode=True, sort_keys=False))
    except pipeline.ValidationError as exc:
        raise ProductionError(str(exc)) from exc


def validate_document(data, root):
    if not isinstance(data, dict) or data.get('kind') != 'production' or data.get('version') != 1:
        raise ProductionError('需要 version=1 的 production 清单')
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,79}', str(data.get('id', ''))):
        raise ProductionError('非法任务 id')
    template = data.get('template')
    if not isinstance(template, dict) or template.get('hash') != digest(template.get('snapshot')):
        raise ProductionError('模板快照与版本指纹不一致，禁止静默更改流程')
    if not isinstance(data.get('binding'), dict) or not isinstance(data['binding'].get('nodes'), dict):
        raise ProductionError('缺少宿主绑定快照')
    chapters = data.get('chapters')
    if not isinstance(chapters, list) or not chapters:
        raise ProductionError('章节列表不能为空')
    ids, outputs, workspaces, numbers = set(), set(), [], []
    for chapter in chapters:
        if not isinstance(chapter, dict) or set(chapter) - {'id', 'params', 'overrides'}:
            raise ProductionError('章节仅可包含 id、params、overrides')
        cid = chapter.get('id')
        if not isinstance(cid, str) or not re.fullmatch(r'ch[0-9]+', cid) or cid in ids:
            raise ProductionError('章节实例 id 非法或重复')
        ids.add(cid)
        params = chapter.get('params')
        if not isinstance(params, dict) or type(params.get('chapter_num')) is not int:
            raise ProductionError('章节参数必须包含整数 chapter_num')
        numbers.append(params['chapter_num'])
        graph = chapter_graph(data, cid)
        expanded_params = graph['params']
        workspace = safe_path(root, expanded_params['chapter_workspace']).resolve()
        expected = safe_path(root, f'工作区/生产任务/{data["id"]}').resolve()
        if not workspace.is_relative_to(expected) or workspace == expected:
            raise ProductionError('章节工作区必须隔离在当前生产任务目录下')
        if any(workspace == w or workspace.is_relative_to(w) or w.is_relative_to(workspace) for w in workspaces):
            raise ProductionError('章节工作区不可重复或互相包含')
        workspaces.append(workspace)
        output_rel = expanded_params['chapter_output'].replace('\\', '/')
        output = safe_path(root, output_rel).resolve()
        if (output_rel.split('/')[0] not in ('正文', 'chapters') or output.suffix != '.md'
                or not any(output.is_relative_to(Path(root).resolve() / base) for base in ('正文', 'chapters'))):
            raise ProductionError('章节正式产物仅允许正文/或 chapters/ 下的 .md 文件')
        if output in outputs:
            raise ProductionError('章节正式产物路径不可重复')
        outputs.add(output)
        if 'author_accept' not in graph['nodes'] or 'novel_stats' not in graph['nodes']:
            raise ProductionError('生产模板必须保留人工放行与统计节点')
        for node in graph['nodes'].values():
            for field in ('inputs', 'outputs', 'inplace'):
                for rel in node.get(field, []):
                    expanded = pipeline._expand_params(rel, graph['params'])
                    if re.search(r'\{[a-zA-Z_]', expanded):
                        raise ProductionError(f'存在未解析路径参数: {expanded}')
                    safe_path(root, expanded)
    if numbers != sorted(set(numbers)) or any(n <= 0 for n in numbers):
        raise ProductionError('章号必须为正整数、唯一且按先后排序')
    safe_path(root, f'工作区/生产任务/{data["id"]}/state.json')
    return data


def create_document(name, chapters, host=None):
    import chapter_templates
    if not isinstance(chapters, list) or not chapters:
        raise ProductionError('章节列表不能为空')
    task_id = 'production-' + uuid.uuid4().hex[:12]
    template = chapter_templates.load_template()
    doc = {'version': 1, 'kind': 'production', 'id': task_id, 'name': name,
           'template': {'id': 'chapter-v1', 'hash': digest(template), 'snapshot': template},
           'binding': {'host': host or registry.detect_host().get('host'), 'nodes': {}}, 'chapters': copy.deepcopy(chapters)}
    for ch in doc['chapters']:
        ch.setdefault('id', f'ch{int(ch["params"]["chapter_num"]):03d}')
        ch.setdefault('overrides', {})
        ch['params']['chapter_workspace'] = f'工作区/生产任务/{task_id}/{ch["id"]}'
        if 'chapter_output' not in ch['params']:
            graph = chapter_templates.instantiate(params=ch['params'])
            ch['params']['chapter_output'] = graph['params']['chapter_output']
    graph = chapter_graph(doc, doc['chapters'][0]['id'])
    for nid, node in graph['nodes'].items():
        if node['kind'] == 'agent':
            doc['binding']['nodes'][nid] = registry.resolve_node_model(node, doc['binding']['host'])
    return doc


def _bytes_hash(raw):
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def _parse_document(root, raw):
    if not isinstance(raw, bytes):
        raise ProductionError('生产清单快照必须是不可变 bytes')
    try:
        data = yaml.safe_load(raw.decode('utf-8-sig'))
    except (yaml.YAMLError, UnicodeError) as exc:
        raise ProductionError(f'无法解析生产清单: {exc}') from exc
    return validate_document(data, root)


def load_document(root, workflow):
    return _parse_document(root, workflow_path(root, workflow).read_bytes())


def _current_document(root, workflow, locked_doc):
    doc = load_document(root, workflow)
    if doc['id'] != locked_doc['id']:
        raise RevisionConflict('持锁期间任务身份已变化，请重新加载')
    return doc


def _state_path(root, doc):
    return safe_path(root, f'工作区/生产任务/{doc["id"]}/state.json')


def _read_state(root, doc):
    path = _state_path(root, doc)
    if not path.exists():
        return {'version': 1, 'task_id': doc['id'], 'chapters': {}}
    try:
        state = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError) as exc:
        raise ProductionError('运行记录损坏，不自动重置') from exc
    if not isinstance(state, dict) or state.get('task_id') != doc['id'] or not isinstance(state.get('chapters'), dict):
        raise ProductionError('运行记录身份不一致')
    return state


def _write_stamp(stat):
    return {'mtime_ns': stat.st_mtime_ns, 'ctime_ns': stat.st_ctime_ns,
            'inode': stat.st_ino, 'device': stat.st_dev, 'size': stat.st_size}


def _atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        binary = isinstance(text, bytes)
        with tempfile.NamedTemporaryFile(mode='wb' if binary else 'w', encoding=None if binary else 'utf-8',
                                         dir=path.parent, delete=False) as f:
            tmp = Path(f.name)
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        written = _write_stamp(tmp.stat())
        os.replace(tmp, path)
        published = _write_stamp(path.stat())
        # rename 在部分文件系统会更新 ctime；其余标识必须仍属于临时文件。
        # 在返回之前冻结发布标识，调用者不能事后把作者的新文件认作自己发布的版本。
        if all(published[key] == written[key] for key in ('mtime_ns', 'inode', 'device', 'size')):
            return published
        return None
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


@contextmanager
def _locked(root, doc):
    path = _state_path(root, doc).with_suffix('.lock')
    safe_path(root, path.relative_to(Path(root).resolve()).as_posix())
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ProductionError('任务正在更新；若上次进程异常退出，请确认无执行者后清理 state.lock') from exc
    try:
        os.write(fd, str(os.getpid()).encode('ascii'))
        os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)


def _write_state(root, doc, state):
    state['updatedAt'] = pipeline.utc_now_iso()
    _atomic(_state_path(root, doc), json.dumps(state, ensure_ascii=False, indent=2))


def _hashes(root, paths, params):
    result = {}
    for rel in paths:
        rel = pipeline._expand_params(rel, params)
        path = safe_path(root, rel)
        result[rel] = pipeline.hash_path(path) if path.exists() else None
    return result


def _fingerprint(graph, nid):
    node = {k: v for k, v in graph['nodes'][nid].items() if not k.startswith('_')}
    return digest({'node': node, 'params': graph['params']})


def _output_versions(root, node, params):
    """内容和写入标识共同作为 start 基线；状态文件时间不参与产物证明。"""
    versions = {}
    for rel, content_hash in _hashes(root, node.get('outputs', []), params).items():
        path = safe_path(root, rel)
        stamps = {}
        if content_hash is not None:
            paths = [path] + (sorted(path.rglob('*')) if path.is_dir() else [])
            for item in paths:
                stamps[item.relative_to(path).as_posix()] = _write_stamp(item.stat())
        versions[rel] = {'hash': content_hash, 'writes': stamps}
    return versions


def _dependencies(doc, saved, instance, graph, nid):
    refs = [(instance, upstream) for upstream in graph['nodes'][nid].get('after', [])]
    pos = next(i for i, ch in enumerate(doc['chapters']) if ch['id'] == instance)
    if pos:
        refs.append((doc['chapters'][pos - 1]['id'], 'novel_stats'))
    signature = {}
    for cid, upstream in refs:
        attempts = saved.get('chapters', {}).get(cid, {}).get('nodes', {}).get(upstream, {}).get('attempts', [])
        last = attempts[-1] if attempts else {}
        signature[f'{cid}/{upstream}'] = last.get('id') if last.get('status') == 'succeeded' else None
    return signature


def _binding_drift(doc, graph):
    if not doc['binding'].get('host'):
        return '未识别任务宿主，需显式配置绑定'
    for nid, node in graph['nodes'].items():
        if node['kind'] != 'agent':
            continue
        planned = doc['binding']['nodes'].get(nid, {})
        current = registry.resolve_node_model(node, doc['binding']['host'])
        if not planned.get('model'):
            return f'节点 {nid} 未配置宿主模型'
        if current.get('model') != planned.get('model') or current.get('tier') != planned.get('tier'):
            return '宿主模型配置已变化；任务绑定未升级，禁止静默换模型'
    return None


def _ordered(nodes):
    done = []
    while len(done) < len(nodes):
        ready = [nid for nid, n in nodes.items() if nid not in done and all(d in done for d in n.get('after', []))]
        if not ready:
            raise ProductionError('模板依赖存在环')
        done.extend(ready)
    return done


def _derive(root, doc, saved):
    outer, inner = {}, {}
    previous_ok = True
    for chapter in doc['chapters']:
        cid = chapter['id']
        graph = chapter_graph(doc, cid)
        records = saved.get('chapters', {}).get(cid, {}).get('nodes', {})
        drift = _binding_drift(doc, graph)
        entries = {}
        for nid in _ordered(graph['nodes']):
            node = graph['nodes'][nid]
            attempts = records.get(nid, {}).get('attempts', [])
            last = attempts[-1] if attempts else {}
            inputs = _hashes(root, node.get('inputs', []), graph['params'])
            outputs = _hashes(root, node.get('outputs', []), graph['params'])
            reason = None
            if last.get('status') == 'running':
                status = 'running'
            elif not previous_ok:
                status, reason = 'blocked', '前一章尚未完成全部生产与人工放行'
            elif any(entries[d]['status'] != 'succeeded' for d in node.get('after', [])):
                status, reason = 'blocked', '上游节点未成功或结果已过期'
            elif any(v is None for v in inputs.values()):
                status, reason = 'blocked', '缺少输入: ' + ', '.join(k for k, v in inputs.items() if v is None)
            elif last.get('status') == 'failed':
                status, reason = 'failed', last.get('error') or '执行失败'
            elif last.get('status') == 'succeeded':
                unchanged = (last.get('definition') == _fingerprint(graph, nid)
                             and last.get('binding') == digest(doc['binding']) and not drift
                             and last.get('dependencies') == _dependencies(doc, saved, cid, graph, nid)
                             and last.get('inputs') == inputs and last.get('outputs') == outputs
                             and all(v is not None for v in outputs.values()))
                status = 'succeeded' if unchanged else 'stale'
                reason = None if unchanged else '输入、产物、任务定义、绑定或上游成功代次已变化，需重跑'
            else:
                status = 'pending-human' if node['kind'] == 'human' else 'pending'
            binding = doc['binding']['nodes'].get(nid, {})
            entries[nid] = {'kind': node['kind'], 'role': node.get('role'), 'status': status,
                            'running': status == 'running', 'runningSince': last.get('started_at'),
                            'staleBecause': reason, 'failedBecause': reason if status == 'failed' else None,
                            'attempt_count': len(attempts), 'attempt_id': last.get('id'),
                            'inputs': inputs, 'outputs': list(outputs),
                            'model': binding.get('model'), 'model_origin': 'task-snapshot',
                            'model_tier': binding.get('tier'), 'model_note': drift or binding.get('note'),
                            'actual_model': last.get('actual_model'),
                            'actual_model_origin': 'host-reported' if last.get('actual_model') else None,
                            'model_evidence': last.get('model_evidence'),
                            'model_evidence_hash': last.get('model_evidence_hash')}
        values = [e['status'] for e in entries.values()]
        if 'running' in values:
            aggregate = 'running'
        elif not previous_ok:
            aggregate = 'blocked'
        elif 'failed' in values:
            aggregate = 'failed'
        elif all(v == 'succeeded' for v in values):
            aggregate = 'succeeded'
        elif 'stale' in values:
            aggregate = 'stale'
        elif 'pending-human' in values:
            aggregate = 'pending-human'
        elif 'pending' in values:
            aggregate = 'pending'
        else:
            aggregate = 'blocked'
        active = next((nid for nid, entry in entries.items() if entry['status'] not in ('succeeded', 'blocked')), None)
        reason = next((e['staleBecause'] for e in entries.values() if e.get('staleBecause')), None)
        outer[cid] = {'kind': 'subworkflow', 'status': aggregate, 'running': aggregate == 'running',
                      'completed': values.count('succeeded'), 'total': len(values), 'active_node': active,
                      'staleBecause': reason, 'failedBecause': reason if aggregate == 'failed' else None,
                      'model_note': drift}
        inner[cid] = {'version': 1, 'task_id': doc['id'], 'instance': cid, 'params': graph['params'],
                      'nodes': entries, 'binding_drift': drift}
        previous_ok = aggregate == 'succeeded'
    return outer, inner


def snapshot(root, workflow, instance=None, *, raw=None):
    root = Path(root).resolve()
    path = workflow_path(root, workflow)
    raw = path.read_bytes() if raw is None else raw
    doc = _parse_document(root, raw)
    revision = _bytes_hash(raw)
    saved = _read_state(root, doc)
    outer, inner = _derive(root, doc, saved)
    metadata = {'id': doc['id'], 'name': doc['name'], 'instance': instance,
                'chapters': [ch['id'] for ch in doc['chapters']], 'template_id': doc['template']['id'],
                'template_hash': doc['template']['hash'], 'binding_host': doc['binding']['host']}
    if instance:
        graph = chapter_graph(doc, instance)
        inner[instance]['production'] = metadata
        return graph, inner[instance], revision
    nodes = {}
    previous = None
    for ch in doc['chapters']:
        cid = ch['id']
        nodes[cid] = {'kind': 'subworkflow', 'role': f'第{ch["params"]["chapter_num"]}章 · {ch["params"]["chapter_title"]}',
                      'after': [previous] if previous else [], 'instance': cid, 'inputs': [], 'outputs': []}
        previous = cid
    return {'version': 1, 'kind': 'production', 'name': doc['name'], 'params': {}, 'nodes': nodes}, {
        'version': 1, 'task_id': doc['id'], 'nodes': outer, 'production': metadata}, revision


def save_chapter(root, workflow, instance, overrides, revision):
    root = Path(root).resolve()
    doc = load_document(root, workflow)
    path = workflow_path(root, workflow)
    with _locked(root, doc):
        raw = path.read_bytes()
        if _bytes_hash(raw) != revision:
            raise RevisionConflict('配置已变化，请保留草稿并重新加载')
        current = _parse_document(root, raw)
        if current['id'] != doc['id']:
            raise RevisionConflict('持锁期间任务身份已变化，请重新加载')
        doc = current
        if any(a.get('status') == 'running' for c in _read_state(root, doc)['chapters'].values()
               for n in c.get('nodes', {}).values() for a in n.get('attempts', [])[-1:]):
            raise ProductionError('任务运行中，不能修改章节要求')
        chapter = next((c for c in doc['chapters'] if c['id'] == instance), None)
        if chapter is None:
            raise ProductionError('任务不包含该章节')
        chapter['overrides'] = copy.deepcopy(overrides)
        validate_document(doc, root)
        if pipeline.hash_file(path) != revision:
            raise RevisionConflict('保存期间配置发生变化')
        _atomic(path, yaml.safe_dump(doc, allow_unicode=True, sort_keys=False))
        return pipeline.hash_file(path)


def start_node(root, workflow, instance, node_id, *, _human=False):
    root = Path(root).resolve()
    doc = load_document(root, workflow)
    with _locked(root, doc):
        doc = _current_document(root, workflow, doc)
        graph = chapter_graph(doc, instance)
        if node_id not in graph['nodes']:
            raise ProductionError('未知节点')
        node = graph['nodes'][node_id]
        if node['kind'] == 'human' and not _human:
            raise ProductionError('人工节点必须通过 accept --confirm 放行')
        saved = _read_state(root, doc)
        if any(a.get('status') == 'running' for c in saved['chapters'].values()
               for n in c.get('nodes', {}).values() for a in n.get('attempts', [])[-1:]):
            raise ProductionError('任务已有运行节点，请先结束该次执行')
        _, inner = _derive(root, doc, saved)
        entry = inner[instance]['nodes'][node_id]
        if entry['status'] in ('blocked', 'running'):
            raise ProductionError(entry.get('staleBecause') or '节点不能启动')
        drift = _binding_drift(doc, graph)
        if drift:
            raise ProductionError(drift)
        actual_host = registry.detect_host().get('host')
        if actual_host and actual_host != doc['binding']['host']:
            raise ProductionError('当前宿主与任务绑定不同，需显式迁移绑定')
        token = uuid.uuid4().hex
        attempt = {'id': token, 'status': 'running', 'started_at': pipeline.utc_now_iso(),
                   'definition': _fingerprint(graph, node_id), 'inputs': entry['inputs'],
                   'binding': digest(doc['binding']),
                   'dependencies': _dependencies(doc, saved, instance, graph, node_id),
                   'output_baseline': _output_versions(root, node, graph['params'])}
        records = saved['chapters'].setdefault(instance, {}).setdefault('nodes', {})
        records.setdefault(node_id, {}).setdefault('attempts', []).append(attempt)
        _write_state(root, doc, saved)
        return token


def _running_attempt(saved, instance, node_id, attempt_id):
    attempts = saved['chapters'].get(instance, {}).get('nodes', {}).get(node_id, {}).get('attempts', [])
    if not attempts or attempts[-1]['id'] != attempt_id or attempts[-1]['status'] != 'running':
        raise ProductionError('执行回执不属于当前运行尝试')
    return attempts[-1]


def _execution_failures(root, doc, saved, instance, graph, node_id, last):
    """finish 和归档前共享冻结契约校验；调用者持有任务锁。"""
    node = graph['nodes'][node_id]
    failures = []
    if (last.get('definition') != _fingerprint(graph, node_id)
            or last.get('inputs') != _hashes(root, node.get('inputs', []), graph['params'])):
        failures.append('执行期间输入或任务定义已变化')
    if last.get('binding') != digest(doc['binding']):
        failures.append('执行期间任务绑定已变化')
    if last.get('dependencies') != _dependencies(doc, saved, instance, graph, node_id):
        failures.append('执行期间上游成功代次已变化')
    outer, inner = _derive(root, doc, saved)
    pos = next(i for i, c in enumerate(doc['chapters']) if c['id'] == instance)
    if pos and outer[doc['chapters'][pos - 1]['id']]['status'] != 'succeeded':
        failures.append('前一章结果已失效')
    if any(inner[instance]['nodes'][d]['status'] != 'succeeded' for d in node.get('after', [])):
        failures.append('上游结果已失效')
    drift = _binding_drift(doc, graph)
    if drift:
        failures.append(drift)
    return failures


def _finish_locked(root, doc, saved, instance, node_id, attempt_id, *, exit_code=0, error=None,
                   actual_model=None, model_evidence=None):
    """只更新内存回执；调用者负责回滚正式稿（如需）后持锁落盘。"""
    last = _running_attempt(saved, instance, node_id, attempt_id)
    graph = chapter_graph(doc, instance)
    node = graph['nodes'][node_id]
    failures = [error or f'进程退出码 {exit_code}'] if exit_code else []
    failures.extend(_execution_failures(root, doc, saved, instance, graph, node_id, last))
    versions = _output_versions(root, node, graph['params'])
    outputs = {rel: version['hash'] for rel, version in versions.items()}
    if not outputs or any(v is None for v in outputs.values()):
        failures.append('执行结束但产物缺失')
    baseline = last.get('output_baseline')
    if baseline is None or any(baseline.get(rel) == version for rel, version in versions.items()):
        failures.append('产物无本次写入证据，不能以旧文件冒充执行')
    failures.extend(pipeline.evaluate_asserts(dict(node, _params=graph['params']), root))
    if actual_model:
        if not model_evidence:
            raise ProductionError('宿主回报实际模型需要同时提供证据路径')
        evidence = safe_path(root, model_evidence)
        if not evidence.is_file():
            raise ProductionError('派发证据文件不存在')
        last.update(actual_model=actual_model, actual_model_origin='host-reported',
                    model_evidence=model_evidence, model_evidence_hash=pipeline.hash_file(evidence))
        planned = doc['binding']['nodes'].get(node_id, {}).get('model')
        if actual_model != planned:
            failures.append('宿主回报实际模型与任务绑定不一致')
    last.update(status='failed' if failures else 'succeeded', finished_at=pipeline.utc_now_iso(),
                exit_code=exit_code, error='；'.join(failures) or None, outputs=outputs)
    return last['status']


def finish_node(root, workflow, instance, node_id, attempt_id, *, exit_code=0, error=None,
                actual_model=None, model_evidence=None):
    root = Path(root).resolve()
    doc = load_document(root, workflow)
    with _locked(root, doc):
        doc = _current_document(root, workflow, doc)
        saved = _read_state(root, doc)
        result = _finish_locked(root, doc, saved, instance, node_id, attempt_id, exit_code=exit_code,
                                error=error, actual_model=actual_model, model_evidence=model_evidence)
        _write_state(root, doc, saved)
        return result


def run_node(root, workflow, instance, node_id):
    doc = load_document(root, workflow)
    graph = chapter_graph(doc, instance)
    node = graph['nodes'].get(node_id, {})
    if node.get('kind') != 'command':
        raise ProductionError('run 仅用于命令节点；agent 由宿主派发，human 需明确批准')
    token = start_node(root, workflow, instance, node_id)
    try:
        proc = subprocess.run(pipeline.build_command_argv(node, graph['params']), cwd=root)
        code, error = proc.returncode, None
    except OSError as exc:
        code, error = 2, str(exc)
    status = finish_node(root, workflow, instance, node_id, token, exit_code=code, error=error)
    return code if code else (0 if status == 'succeeded' else 1)


def accept_node(root, workflow, instance, node_id='author_accept', *, confirmed=False):
    if not confirmed:
        raise ProductionError('必须由作者明确批准 --confirm')
    root = Path(root).resolve()
    doc = load_document(root, workflow)
    graph = chapter_graph(doc, instance)
    if graph['nodes'].get(node_id, {}).get('kind') != 'human':
        raise ProductionError('该节点不是人工确认节点')
    token = start_node(root, workflow, instance, node_id, _human=True)
    # start 已释放锁；最后校验、备份、发布、回执/回滚使用同一把锁，不能重入 finish_node。
    with _locked(root, doc):
        saved = _read_state(root, doc)
        last = _running_attempt(saved, instance, node_id, token)
        published_version, old_bytes, dst = None, None, None
        try:
            current = _current_document(root, workflow, doc)
            graph = chapter_graph(current, instance)
            node = graph['nodes'][node_id]
            src_rel = pipeline._expand_params(node['inputs'][0], graph['params'])
            dst_rel = pipeline._expand_params(node['outputs'][0], graph['params'])
            src, dst = safe_path(root, src_rel), safe_path(root, dst_rel)
            # 一次读取的不可变字节既用于哈希核对，也用于发布；不再二次读取源稿。
            source_bytes = src.read_bytes()
            source_hash = _bytes_hash(source_bytes)
            if source_hash != last['inputs'].get(src_rel):
                raise ProductionError('取得的源稿字节与本次批准冻结的输入不一致')
            failures = _execution_failures(root, current, saved, instance, graph, node_id, last)
            if failures:
                raise ProductionError('；'.join(failures))
            backup_rel = None
            old_bytes = dst.read_bytes() if dst.exists() else None
            target_versions = _output_versions(root, node, graph['params'])
            old_hash = _bytes_hash(old_bytes) if old_bytes is not None else None
            if (target_versions != last.get('output_baseline')
                    or target_versions[dst_rel]['hash'] != old_hash):
                raise ProductionError('正式稿已偏离批准时的目标版本，保留作者修改')
            if old_bytes is not None:
                backup_rel = f'工作区/生产任务/{doc["id"]}/backups/{instance}-{token}.md'
                _atomic(safe_path(root, backup_rel), old_bytes)
            # 备份期间也可能发生外部编辑，正式替换之前再次校验。
            current = _current_document(root, workflow, doc)
            graph = chapter_graph(current, instance)
            failures = _execution_failures(root, current, saved, instance, graph, node_id, last)
            if failures:
                raise ProductionError('；'.join(failures))
            if _output_versions(root, node, graph['params']) != target_versions:
                raise ProductionError('备份或校验期间正式稿已变化，保留作者修改')
            published_stamp = _atomic(dst, source_bytes)
            if published_stamp is None:
                raise ProductionError('无法确认本次发布的文件身份，保留当前正式稿')
            published_version = {dst_rel: {'hash': source_hash, 'writes': {'.': published_stamp}}}
            archive_node = {'outputs': [dst_rel]}
            current = _current_document(root, workflow, doc)
            result = _finish_locked(root, current, saved, instance, node_id, token)
            if result != 'succeeded':
                raise ProductionError(last['error'])
            if _output_versions(root, archive_node, {}) != published_version:
                raise ProductionError('归档产物已被外部修改，保留作者版本')
            last['archive'] = {'source': src_rel, 'source_hash': source_hash,
                               'output': dst_rel, 'backup': backup_rel}
            _write_state(root, doc, saved)
            return result
        except (OSError, ValueError) as exc:
            # 只撤销仍属于本 attempt 的字节和写入标识；删除/重建也视作所有权丢失。
            # 外部编辑不配合任务锁，版本检查与 replace/unlink 之间仍非事务性的 CAS。
            try:
                if (published_version is not None
                        and _output_versions(root, archive_node, {}) == published_version):
                    if old_bytes is None:
                        dst.unlink(missing_ok=True)
                    else:
                        _atomic(dst, old_bytes)
            except (OSError, ValueError) as rollback_exc:
                exc = ProductionError(f'{exc}；无法安全回滚正式稿: {rollback_exc}')
            last.pop('archive', None)
            last.update(status='failed', finished_at=pipeline.utc_now_iso(), exit_code=2,
                        error=str(exc), outputs={})
            _write_state(root, doc, saved)
            return 'failed'


def node_prompt(root, workflow, instance, node_id):
    doc = load_document(root, workflow)
    graph = chapter_graph(doc, instance)
    node = graph['nodes'].get(node_id)
    if node is None:
        raise ProductionError('未知节点')
    binding = doc['binding']['nodes'].get(node_id, {})
    params = graph['params']
    base = [sys.executable, str(Path(__file__).resolve()), 'start', '--project', str(Path(root).resolve()),
            '--workflow', workflow, '--instance', instance, '--node', node_id]
    command = subprocess.list2cmdline(base) if os.name == 'nt' else __import__('shlex').join(base)
    inputs = [pipeline._expand_params(x, params) for x in node.get('inputs', [])]
    outputs = [pipeline._expand_params(x, params) for x in node.get('outputs', [])]
    return '\n'.join([
        f'生产任务 {doc["name"]} / {instance} / {node_id}',
        f'宿主绑定：{doc["binding"]["host"]}；计划模型：{binding.get("model") or "不适用/未配置"}（不是实际派发证明）',
        f'角色：{node.get("subagent_type") or node.get("role") or node["kind"]}',
        '技能：' + ', '.join(node.get('skills', [])), '只读输入：' + ', '.join(inputs),
        '输出：' + ', '.join(outputs), '质量门禁：' + json.dumps(node.get('assert', {}), ensure_ascii=False),
        pipeline._expand_params(node.get('prompt') or node.get('ask') or '', params),
        f'开始前执行：{command}',
        '保存 start 返回的 attempt；结束后调用相同实例的 finish --attempt TOKEN --exit-code N。',
        '不得以 status/reconcile 或文件存在代替执行完成回执。模型未注册或派发无法遵循绑定时停止并报错，不得静默替换。',
        'human 节点只允许作者批准后 accept --confirm；command 节点使用 run（朱雀API会上传正文并收费）。',
    ])


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='多章生产任务：显式宿主执行与人工放行')
    parser.add_argument('action', choices=['status', 'prompt', 'start', 'finish', 'run', 'accept'])
    parser.add_argument('--project', required=True)
    parser.add_argument('--workflow', default='production.yaml')
    parser.add_argument('--instance')
    parser.add_argument('--node')
    parser.add_argument('--attempt')
    parser.add_argument('--exit-code', type=int, default=0)
    parser.add_argument('--error')
    parser.add_argument('--actual-model')
    parser.add_argument('--model-evidence')
    parser.add_argument('--confirm', action='store_true')
    args = parser.parse_args()
    root = Path(args.project).resolve()
    try:
        if args.action == 'status':
            print(json.dumps(snapshot(root, args.workflow, args.instance)[1], ensure_ascii=False, indent=2))
            return 0
        if not args.instance or not args.node:
            parser.error('执行节点需要 --instance 和 --node')
        if args.action == 'prompt':
            print(node_prompt(root, args.workflow, args.instance, args.node))
        elif args.action == 'start':
            print(json.dumps({'attempt': start_node(root, args.workflow, args.instance, args.node)}))
        elif args.action == 'finish':
            result = finish_node(root, args.workflow, args.instance, args.node, args.attempt,
                                 exit_code=args.exit_code, error=args.error,
                                 actual_model=args.actual_model, model_evidence=args.model_evidence)
            print(result)
            return 0 if result == 'succeeded' else 1
        elif args.action == 'run':
            return run_node(root, args.workflow, args.instance, args.node)
        elif args.action == 'accept':
            result = accept_node(root, args.workflow, args.instance, args.node, confirmed=args.confirm)
            return 0 if result == 'succeeded' else 1
        return 0
    except (ValueError, OSError) as exc:
        print(f'生产任务错误: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
