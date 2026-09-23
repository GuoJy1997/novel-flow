"""生产实例的状态必须来自本轮执行，不以旧文件冒充成功。仅操作临时目录。"""
import copy
import hashlib
import importlib
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml


def test_production_engine_is_available():
    assert importlib.util.find_spec('production') is not None, '缺少独立生产实例引擎'


def engine():
    return importlib.import_module('production')


def document(p):
    # 保留真实十节点、技能、门禁与宿主绑定，server 测试也使用此夹具。
    import chapter_templates
    template = chapter_templates.load_template()
    return {'version': 1, 'kind': 'production', 'id': 'test-batch', 'name': '测试双章',
            'template': {'id': 'chapter-v1', 'snapshot': template, 'hash': p.digest(template)},
            'binding': {'host': 'qoder', 'nodes': {
                nid: p.registry.resolve_node_model(node, host='qoder')
                for nid, node in template['nodes'].items() if node['kind'] == 'agent'}},
            'chapters': [{'id': f'ch{n:03d}', 'params': {'chapter_num': n, 'chapter_title': f'title{n}',
                          'target_words': 500,
                          'chapter_workspace': f'工作区/生产任务/test-batch/ch{n:03d}',
                          'chapter_output': f'正文/{n}.md'}, 'overrides': {}} for n in (51, 52)]}


def write_manifest(root, doc):
    raw = yaml.safe_dump(doc, allow_unicode=True).encode('utf-8')
    (root / 'production.yaml').write_bytes(raw)
    return raw


def put(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


SCORES = 'SCORES: ' + json.dumps(dict.fromkeys(
    ('overall', 'persona', 'addressing', 'epistemic_boundary', 'consistency',
     'dialogue_balance', 'lore', 'pacing', 'hook', 'ooc'), 95))
DRAFT = '山风吹过长街。' * 80


@pytest.fixture
def batch(tmp_path, monkeypatch):
    p = engine()
    doc = document(p)
    write_manifest(tmp_path, doc)
    put(tmp_path / '资产/voice_sample.md', '作者样本，仅测试。')

    def external_command(argv, *, cwd):
        # 唯一 mock 是外部进程边界：绝不运行朱雀收费 API。
        assert Path(cwd).resolve() == tmp_path.resolve()
        script = Path(argv[1]).name
        assert script in ('check_humanness.py', 'check_zhuque_api.py', 'novel_stats.py')
        output = tmp_path / argv[argv.index('--output') + 1]
        assert output.resolve().is_relative_to(tmp_path.resolve())
        if script == 'novel_stats.py':
            assert (tmp_path / argv[argv.index('--chapter') + 1]).is_file()
            put(output, json.dumps({'words': 560}))
        else:
            assert (tmp_path / argv[argv.index('--input') + 1]).is_file()
            put(output, SCORES)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(p.subprocess, 'run', external_command)
    return p, tmp_path, doc


def status(p, root, instance=None):
    return p.snapshot(root, 'production.yaml', instance)[1]


def output_path(p, root, nid, instance='ch051'):
    graph = p.chapter_graph(p.load_document(root, 'production.yaml'), instance)
    return root / graph['nodes'][nid]['outputs'][0]


def write_outputs(p, root, nid, instance='ch051', text=None):
    graph = p.chapter_graph(p.load_document(root, 'production.yaml'), instance)
    node = graph['nodes'][nid]
    if text is None:
        text = SCORES if 'min_score' in node.get('assert', {}) else DRAFT
    for rel in node['outputs']:
        put(root / rel, text)


def execute(p, root, nid, instance='ch051'):
    graph = p.chapter_graph(p.load_document(root, 'production.yaml'), instance)
    if graph['nodes'][nid]['kind'] == 'command':
        assert p.run_node(root, 'production.yaml', instance, nid) == 0
    else:
        token = p.start_node(root, 'production.yaml', instance, nid)
        write_outputs(p, root, nid, instance)
        assert p.finish_node(root, 'production.yaml', instance, nid, token) == 'succeeded'


def run_to_review(p, root, instance='ch051'):
    for nid in ('explore_context', 'scene_beats', 'draft_chapter', 'deai_polish',
                'check_zhuque', 'zhuque_api_final', 'audit_persona', 'review_qc'):
        execute(p, root, nid, instance)


def complete(p, root, instance='ch051'):
    run_to_review(p, root, instance)
    assert p.accept_node(root, 'production.yaml', instance, confirmed=True) == 'succeeded'
    execute(p, root, 'novel_stats', instance)


@contextmanager
def after_return(function, action, predicate=lambda frame: True):
    """在真实调用返回处交错外部文件编辑；不 mock 状态、锁、哈希或校验。"""
    previous = sys.gettrace()
    fired = False

    def trace(frame, event, arg):
        nonlocal fired
        if fired or frame.f_code is not function.__code__:
            return previous(frame, event, arg) if previous else None
        frame.f_trace_lines = False
        if event == 'return' and predicate(frame):
            fired = True
            action()
        return trace

    sys.settrace(trace)
    try:
        yield
    finally:
        sys.settrace(previous)
    assert fired, '竞态测试未到达预定的真实 IO 边界'


def test_old_outputs_do_not_count_as_this_run_and_reads_do_not_write(batch):
    p, root, _ = batch
    write_outputs(p, root, 'explore_context')
    before = {str(x): x.read_bytes() for x in root.rglob('*') if x.is_file()}
    assert status(p, root, 'ch051')['nodes']['explore_context']['status'] == 'pending'
    assert status(p, root)['nodes']['ch052']['status'] == 'blocked'
    assert before == {str(x): x.read_bytes() for x in root.rglob('*') if x.is_file()}


def test_serial_execution_requires_human_accept_and_stats_for_four_chapters(batch):
    p, root, doc = batch
    for n in (53, 54):
        chapter = copy.deepcopy(doc['chapters'][0])
        chapter['id'] = f'ch{n:03d}'
        chapter['params'].update(chapter_num=n, chapter_title=f'title{n}',
                                 chapter_workspace=f'工作区/生产任务/test-batch/ch{n:03d}',
                                 chapter_output=f'正文/{n}.md')
        doc['chapters'].append(chapter)
    write_manifest(root, doc)
    for n in range(51, 55):
        cid = f'ch{n:03d}'
        if n < 54:
            with pytest.raises(ValueError):
                p.start_node(root, 'production.yaml', f'ch{n+1:03d}', 'explore_context')
        run_to_review(p, root, cid)
        assert status(p, root, cid)['nodes']['author_accept']['status'] == 'pending-human'
        with pytest.raises(ValueError):
            p.accept_node(root, 'production.yaml', cid, confirmed=False)
        assert p.accept_node(root, 'production.yaml', cid, confirmed=True) == 'succeeded'
        if n < 54:
            assert status(p, root)['nodes'][f'ch{n+1:03d}']['status'] == 'blocked'
        execute(p, root, 'novel_stats', cid)
        assert status(p, root)['nodes'][cid]['status'] == 'succeeded'
        assert (root / f'正文/{n}.md').read_text(encoding='utf-8') == DRAFT
    assert all(e['status'] == 'succeeded' for e in status(p, root)['nodes'].values())


def test_failure_retry_and_attempt_token_isolation(batch):
    p, root, _ = batch
    first = p.start_node(root, 'production.yaml', 'ch051', 'explore_context')
    assert status(p, root)['nodes']['ch051']['status'] == 'running'
    with pytest.raises(ValueError):
        p.start_node(root, 'production.yaml', 'ch051', 'explore_context')
    p.finish_node(root, 'production.yaml', 'ch051', 'explore_context', first, exit_code=2, error='网络失败')
    assert status(p, root)['nodes']['ch051']['status'] == 'failed'
    second = p.start_node(root, 'production.yaml', 'ch051', 'explore_context')
    with pytest.raises(ValueError):
        p.finish_node(root, 'production.yaml', 'ch051', 'explore_context', first)
    p.finish_node(root, 'production.yaml', 'ch051', 'explore_context', second, exit_code=1, error='重试失败')
    node = status(p, root, 'ch051')['nodes']['explore_context']
    assert node['attempt_count'] == 2
    assert '重试失败' in node['failedBecause']


def test_upstream_change_invalidates_success_and_blocks_next_chapter(batch):
    p, root, _ = batch
    complete(p, root)
    execute(p, root, 'explore_context', 'ch052')
    (root / '正文/51.md').write_text('externally changed', encoding='utf-8')
    assert status(p, root)['nodes']['ch051']['status'] == 'stale'
    assert status(p, root)['nodes']['ch052']['status'] == 'blocked'


def test_finish_without_outputs_fails_instead_of_turning_green(batch):
    p, root, _ = batch
    token = p.start_node(root, 'production.yaml', 'ch051', 'explore_context')
    assert p.finish_node(root, 'production.yaml', 'ch051', 'explore_context', token) == 'failed'


def test_existing_outputs_and_touching_state_cannot_pass_finish(batch):
    p, root, _ = batch
    write_outputs(p, root, 'explore_context')
    token = p.start_node(root, 'production.yaml', 'ch051', 'explore_context')
    (root / '工作区/生产任务/test-batch/state.json').touch()
    assert p.finish_node(root, 'production.yaml', 'ch051', 'explore_context', token) == 'failed'
    assert '本次' in status(p, root, 'ch051')['nodes']['explore_context']['failedBecause']


def test_identical_bytes_with_fresh_file_identity_can_pass(batch):
    p, root, _ = batch
    write_outputs(p, root, 'explore_context')
    output = output_path(p, root, 'explore_context')
    old_hash = hashlib.sha256(output.read_bytes()).hexdigest()
    token = p.start_node(root, 'production.yaml', 'ch051', 'explore_context')
    replacement = output.with_suffix('.new')
    replacement.write_bytes(output.read_bytes())
    os.replace(replacement, output)
    assert hashlib.sha256(output.read_bytes()).hexdigest() == old_hash
    assert p.finish_node(root, 'production.yaml', 'ch051', 'explore_context', token) == 'succeeded'


def test_same_bytes_upstream_rerun_never_resurrects_downstream(batch):
    p, root, _ = batch
    complete(p, root)
    execute(p, root, 'explore_context', 'ch052')
    execute(p, root, 'explore_context')
    nodes = status(p, root, 'ch051')['nodes']
    assert nodes['scene_beats']['status'] == 'stale'
    assert nodes['author_accept']['status'] != 'succeeded'
    assert status(p, root)['nodes']['ch052']['status'] == 'blocked'
    complete(p, root)
    assert status(p, root, 'ch052')['nodes']['explore_context']['status'] == 'stale'
    execute(p, root, 'explore_context', 'ch052')
    assert status(p, root, 'ch052')['nodes']['explore_context']['status'] == 'succeeded'


def test_previous_chapter_terminal_attempt_invalidates_next_chapter(batch):
    p, root, _ = batch
    complete(p, root)
    execute(p, root, 'explore_context', 'ch052')
    execute(p, root, 'novel_stats')
    assert status(p, root, 'ch052')['nodes']['explore_context']['status'] == 'stale'


@pytest.mark.parametrize('when', ['running', 'succeeded'])
def test_binding_fingerprint_is_frozen_per_attempt(batch, when):
    p, root, doc = batch
    token = p.start_node(root, 'production.yaml', 'ch051', 'explore_context')
    write_outputs(p, root, 'explore_context')
    if when == 'succeeded':
        assert p.finish_node(root, 'production.yaml', 'ch051', 'explore_context', token) == 'succeeded'
    doc['binding']['nodes']['explore_context']['note'] = '显式更新绑定快照'
    write_manifest(root, doc)
    if when == 'running':
        assert p.finish_node(root, 'production.yaml', 'ch051', 'explore_context', token) == 'failed'
    else:
        assert status(p, root, 'ch051')['nodes']['explore_context']['status'] == 'stale'


def test_finish_rereads_manifest_after_lock(batch):
    p, root, doc = batch
    token = p.start_node(root, 'production.yaml', 'ch051', 'explore_context')
    write_outputs(p, root, 'explore_context')
    doc['binding']['nodes']['explore_context']['note'] = '并发变更'
    with after_return(p.load_document, lambda: write_manifest(root, doc)):
        assert p.finish_node(root, 'production.yaml', 'ch051', 'explore_context', token) == 'failed'


def test_model_evidence_is_only_host_report_and_hash_is_preserved(batch):
    p, root, doc = batch
    token = p.start_node(root, 'production.yaml', 'ch051', 'explore_context')
    write_outputs(p, root, 'explore_context')
    evidence = root / 'dispatch.json'
    evidence.write_bytes(b'{"receipt":"host-reported"}')
    model = doc['binding']['nodes']['explore_context']['model']
    assert p.finish_node(root, 'production.yaml', 'ch051', 'explore_context', token,
                         actual_model=model, model_evidence='dispatch.json') == 'succeeded'
    node = status(p, root, 'ch051')['nodes']['explore_context']
    assert node['actual_model'] == model
    assert node['actual_model_origin'] == 'host-reported'
    assert node['model_evidence_hash'] == 'sha256:' + hashlib.sha256(evidence.read_bytes()).hexdigest()


def test_input_changed_while_running_cannot_be_accepted(batch):
    p, root, doc = batch
    put(root / 'source.txt', 'before')
    doc['chapters'][0]['overrides'] = {'explore_context': {'inputs_add': ['source.txt']}}
    write_manifest(root, doc)
    token = p.start_node(root, 'production.yaml', 'ch051', 'explore_context')
    put(root / 'source.txt', 'after')
    write_outputs(p, root, 'explore_context')
    assert p.finish_node(root, 'production.yaml', 'ch051', 'explore_context', token) == 'failed'


@pytest.mark.parametrize('nid,text', [('explore_context', '太短'), ('audit_persona', 'SCORES: {"overall": 99}')])
def test_real_pipeline_quality_gates_are_not_mocked(batch, nid, text):
    p, root, _ = batch
    if nid == 'audit_persona':
        for upstream in ('explore_context', 'scene_beats', 'draft_chapter', 'deai_polish', 'check_zhuque', 'zhuque_api_final'):
            execute(p, root, upstream)
    token = p.start_node(root, 'production.yaml', 'ch051', nid)
    write_outputs(p, root, nid, text=text)
    assert p.finish_node(root, 'production.yaml', 'ch051', nid, token) == 'failed'


@pytest.mark.parametrize('mutate', [
    lambda d: d['template']['snapshot']['nodes'].pop('novel_stats'),
    lambda d: d['chapters'][0]['params'].update(chapter_output='../outside.md'),
    lambda d: d['chapters'][1]['params'].update(chapter_workspace=d['chapters'][0]['params']['chapter_workspace']),
    lambda d: d['chapters'][0]['overrides'].update(explore_context={'model': 'wrong'}),
])
def test_manifest_rejects_tamper_and_escaping_paths(batch, mutate):
    p, root, doc = batch
    mutate(doc)
    with pytest.raises(ValueError):
        p.validate_document(doc, root)


@pytest.mark.parametrize('output', ['production.yaml', '工作区/生产任务/test-batch/state.json',
                                   '工作区/生产任务/other/ch051/draft.md', '正文/not-markdown.txt',
                                   '{voice_sample}'])
def test_formal_outputs_are_only_markdown_in_chapter_directories(batch, output):
    p, root, doc = batch
    doc['chapters'][0]['params']['chapter_output'] = output
    with pytest.raises(ValueError):
        p.validate_document(doc, root)


def test_expanded_outputs_cannot_alias(batch):
    p, root, doc = batch
    doc['chapters'][0]['params'].update(chapter_output='正文/{chapter_title}.md', chapter_title='same')
    doc['chapters'][1]['params'].update(chapter_output='正文/same.md')
    with pytest.raises(ValueError):
        p.validate_document(doc, root)


def test_expanded_workspace_cannot_alias(batch):
    p, root, doc = batch
    doc['chapters'][0]['params']['chapter_workspace'] = '工作区/生产任务/test-batch/{chapter_title}'
    doc['chapters'][1]['params']['chapter_workspace'] = '工作区/生产任务/test-batch/title51'
    with pytest.raises(ValueError):
        p.validate_document(doc, root)


def test_previous_output_uses_previous_chapter_parameters(batch):
    p, root, doc = batch
    for ch in doc['chapters']:
        ch['params']['chapter_output'] = 'chapters/{chapter_pad3}_{chapter_title}.md'
    p.validate_document(doc, root)
    inputs = p.chapter_graph(doc, 'ch052')['nodes']['explore_context']['inputs']
    assert 'chapters/051_title51.md' in inputs
    assert 'chapters/052_title52.md' not in inputs


def test_chapter_edits_require_revision_and_cannot_change_template(batch):
    p, root, _ = batch
    _, _, revision = p.snapshot(root, 'production.yaml', 'ch051')
    with pytest.raises(ValueError):
        p.save_chapter(root, 'production.yaml', 'ch051', {'explore_context': {'model': 'wrong'}}, revision)
    with pytest.raises(ValueError):
        p.save_chapter(root, 'production.yaml', 'ch051', {}, 'outdated')
    updated = p.save_chapter(root, 'production.yaml', 'ch051', {'explore_context': {'inputs_add': ['new-source.txt']}}, revision)
    assert updated != revision
    assert 'new-source.txt' not in p.snapshot(root, 'production.yaml', 'ch052')[0]['nodes']['explore_context']['inputs']


@pytest.mark.parametrize('instance', [None, 'ch051'])
def test_snapshot_raw_bytes_supply_graph_revision_and_metadata(batch, instance):
    p, root, doc = batch
    raw = (root / 'production.yaml').read_bytes()
    doc['name'] = '磁盘较新版本'
    write_manifest(root, doc)
    graph, state, revision = p.snapshot(root, 'production.yaml', instance, raw=raw)
    assert revision == 'sha256:' + hashlib.sha256(raw).hexdigest()
    assert state['production'] == {'id': 'test-batch', 'name': '测试双章', 'instance': instance,
                                   'chapters': ['ch051', 'ch052'], 'template_id': 'chapter-v1',
                                   'template_hash': doc['template']['hash'], 'binding_host': 'qoder'}
    if instance is None:
        assert graph['name'] == '测试双章'


def test_snapshot_disk_revision_is_not_reread_after_parsing(batch):
    p, root, doc = batch
    raw = (root / 'production.yaml').read_bytes()
    doc['name'] = '并发新版本'
    with after_return(p._derive, lambda: write_manifest(root, doc)):
        graph, _, revision = p.snapshot(root, 'production.yaml')
    assert graph['name'] == '测试双章'
    assert revision == 'sha256:' + hashlib.sha256(raw).hexdigest()


def test_save_rereads_current_document_under_lock(batch):
    p, root, doc = batch
    newer = copy.deepcopy(doc)
    newer['name'] = '不能被陈旧副本覆盖的新名称'
    newer_raw = yaml.safe_dump(newer, allow_unicode=True).encode('utf-8')
    revision = 'sha256:' + hashlib.sha256(newer_raw).hexdigest()
    with after_return(p.load_document, lambda: write_manifest(root, newer)):
        p.save_chapter(root, 'production.yaml', 'ch051', {'scene_beats': {'prompt_append': '新要求'}}, revision)
    saved = p.load_document(root, 'production.yaml')
    assert saved['name'] == newer['name']
    assert saved['chapters'][0]['overrides']['scene_beats']['prompt_append'] == '新要求'


@pytest.mark.parametrize('change', ['source', 'definition', 'binding', 'upstream'])
def test_accept_validates_frozen_inputs_before_replacing_formal_draft(batch, change):
    p, root, doc = batch
    run_to_review(p, root)
    formal = root / '正文/51.md'
    put(formal, '已有正式稿')
    source = output_path(p, root, 'deai_polish')

    def edit_after_start():
        if change == 'source':
            put(source, '未审核的新字节' * 100)
        elif change == 'upstream':
            put(output_path(p, root, 'review_qc'), SCORES + '\n外部修改')
        elif change == 'definition':
            doc['chapters'][0]['overrides']['author_accept'] = {'inputs_add': ['额外资料.md']}
            put(root / '额外资料.md', 'new')
            write_manifest(root, doc)
        else:
            doc['binding']['nodes']['explore_context']['note'] = '绑定已更改'
            write_manifest(root, doc)

    with after_return(p.start_node, edit_after_start):
        assert p.accept_node(root, 'production.yaml', 'ch051', confirmed=True) == 'failed'
    assert formal.read_text(encoding='utf-8') == '已有正式稿'
    saved = p._read_state(root, doc)
    assert saved['chapters']['ch051']['nodes']['author_accept']['attempts'][-1]['status'] == 'failed'
    # 外部编辑撤回后可重新审核；上游重新执行而非伪造状态。
    write_manifest(root, document(p))
    run_to_review(p, root)
    assert p.accept_node(root, 'production.yaml', 'ch051', confirmed=True) == 'succeeded'


@pytest.mark.parametrize('has_old', [True, False])
def test_accept_rolls_back_if_input_changes_after_publication(batch, has_old):
    p, root, doc = batch
    run_to_review(p, root)
    formal = root / '正文/51.md'
    if has_old:
        put(formal, '已有正式稿')
    report = output_path(p, root, 'review_qc')

    def edit_during_publication():
        # 发布及最后校验仍在真实任务锁内，旧稿已提前备份。
        assert (root / '工作区/生产任务/test-batch/state.lock').exists()
        if has_old:
            backups = list((root / '工作区/生产任务/test-batch/backups').glob('*.md'))
            assert len(backups) == 1
            assert backups[0].read_text(encoding='utf-8') == '已有正式稿'
        put(report, SCORES + '\n并发改稿')

    with after_return(p._atomic, edit_during_publication,
                      lambda frame: frame.f_locals['path'] == formal):
        assert p.accept_node(root, 'production.yaml', 'ch051', confirmed=True) == 'failed'
    if has_old:
        assert formal.read_text(encoding='utf-8') == '已有正式稿'
    else:
        assert not formal.exists()
    last = p._read_state(root, doc)['chapters']['ch051']['nodes']['author_accept']['attempts'][-1]
    assert last['status'] == 'failed'


def assert_failed_archive(p, root, doc):
    last = p._read_state(root, doc)['chapters']['ch051']['nodes']['author_accept']['attempts'][-1]
    assert last['status'] == 'failed'
    assert last['outputs'] == {}
    assert 'archive' not in last


IDENTITY_FIELDS = ('st_ino', 'st_dev', 'st_size', 'st_mtime_ns', 'st_ctime_ns')


def identity(stat):
    """作者正式稿的身份标识。

    st_atime 会被任何读取改动——实现的发布前校验要读它，本测试断言前一行也要读它，
    因此整份 stat 相等是永远无法稳定成立的判据。inode/设备/大小/mtime/ctime 才真正证明
    文件没有被替换或改写：覆盖发布走 os.replace，会换掉 inode 并前移 mtime/ctime。
    """
    return {field: getattr(stat, field) for field in IDENTITY_FIELDS}


@pytest.mark.parametrize('has_old', [True, False])
def test_accept_preserves_target_changed_after_start(batch, has_old):
    p, root, doc = batch
    run_to_review(p, root)
    formal = root / '正文/51.md'
    if has_old:
        put(formal, 'ORIGINAL')
    with after_return(p.start_node, lambda: put(formal, 'AUTHOR_EDIT_AFTER_START')):
        result = p.accept_node(root, 'production.yaml', 'ch051', confirmed=True)
    assert formal.read_text(encoding='utf-8') == 'AUTHOR_EDIT_AFTER_START'
    assert result == 'failed'
    assert_failed_archive(p, root, doc)


@pytest.mark.parametrize('change', ['write', 'same_bytes', 'delete'])
def test_accept_preserves_target_changed_during_backup(batch, change):
    p, root, doc = batch
    run_to_review(p, root)
    formal = root / '正文/51.md'
    put(formal, 'ORIGINAL')
    author_stat = None

    def edit_during_backup():
        nonlocal author_stat
        if change == 'delete':
            formal.unlink()
        elif change == 'same_bytes':
            replacement = formal.with_suffix('.author')
            put(replacement, 'ORIGINAL')
            os.replace(replacement, formal)
        else:
            put(formal, 'AUTHOR_EDIT_DURING_BACKUP')
        author_stat = formal.stat() if formal.exists() else None

    with after_return(p._atomic, edit_during_backup,
                      lambda frame: frame.f_locals['path'].parent.name == 'backups'):
        result = p.accept_node(root, 'production.yaml', 'ch051', confirmed=True)
    if change == 'delete':
        assert not formal.exists()
    else:
        assert formal.read_text(encoding='utf-8') == (
            'ORIGINAL' if change == 'same_bytes' else 'AUTHOR_EDIT_DURING_BACKUP')
        assert identity(formal.stat()) == identity(author_stat)
    assert result == 'failed'
    assert_failed_archive(p, root, doc)
    backups = list((root / '工作区/生产任务/test-batch/backups').glob('*.md'))
    assert len(backups) == 1
    assert backups[0].read_bytes() == b'ORIGINAL'


@pytest.mark.parametrize('has_old', [True, False])
def test_accept_rechecks_target_after_final_dependency_check(batch, has_old):
    p, root, doc = batch
    run_to_review(p, root)
    formal = root / '正文/51.md'
    if has_old:
        put(formal, 'ORIGINAL')
    with after_return(p._execution_failures, lambda: put(formal, 'AUTHOR_EDIT_BEFORE_PUBLISH'),
                      lambda frame: frame.f_back.f_code is p.accept_node.__code__
                      and 'backup_rel' in frame.f_back.f_locals):
        result = p.accept_node(root, 'production.yaml', 'ch051', confirmed=True)
    assert formal.read_text(encoding='utf-8') == 'AUTHOR_EDIT_BEFORE_PUBLISH'
    assert result == 'failed'
    assert_failed_archive(p, root, doc)


@pytest.mark.parametrize('has_old', [True, False])
@pytest.mark.parametrize('change', ['write', 'delete', 'recreate', 'same_bytes'])
@pytest.mark.parametrize('when', ['publication', 'finish'])
def test_accept_rollback_preserves_author_target(batch, has_old, change, when):
    p, root, doc = batch
    run_to_review(p, root)
    formal = root / '正文/51.md'
    if has_old:
        put(formal, 'ORIGINAL')
    report = output_path(p, root, 'review_qc')
    author_bytes = DRAFT.encode('utf-8') if change == 'same_bytes' else b'AUTHOR_EDIT_AFTER_PUBLISH'
    author_stat = None

    def edit_after_publication():
        nonlocal author_stat
        assert formal.read_text(encoding='utf-8') == DRAFT
        assert (root / '工作区/生产任务/test-batch/state.lock').exists()
        if change in ('delete', 'recreate', 'same_bytes'):
            formal.unlink()
        if change != 'delete':
            formal.write_bytes(author_bytes)
            author_stat = formal.stat()
        if when == 'publication':
            # 真实上游变更触发回滚，不伪造校验或 finish 结果。
            put(report, SCORES + '\nCHANGED_AFTER_PUBLISH')
        # finish 返回后则由最后的目标版本校验触发失败。

    function = p._atomic if when == 'publication' else p._finish_locked
    predicate = (lambda frame: frame.f_locals['path'] == formal) if when == 'publication' else (
        lambda frame: frame.f_locals['node_id'] == 'author_accept')
    with after_return(function, edit_after_publication, predicate):
        result = p.accept_node(root, 'production.yaml', 'ch051', confirmed=True)
    if change == 'delete':
        assert not formal.exists()
    else:
        assert formal.read_bytes() == author_bytes
        assert identity(formal.stat()) == identity(author_stat)
    assert result == 'failed'
    assert_failed_archive(p, root, doc)


def test_accept_checks_obtained_source_bytes_even_if_disk_is_restored(batch):
    p, root, _ = batch
    run_to_review(p, root)
    source = output_path(p, root, 'deai_polish')
    reviewed = source.read_bytes()
    formal = root / '正文/51.md'
    put(formal, '已有正式稿')
    with after_return(p.start_node, lambda: put(source, '未审核字节' * 100)):
        with after_return(Path.read_bytes, lambda: source.write_bytes(reviewed),
                          lambda frame: frame.f_locals['self'] == source):
            assert p.accept_node(root, 'production.yaml', 'ch051', confirmed=True) == 'failed'
    assert source.read_bytes() == reviewed
    assert formal.read_text(encoding='utf-8') == '已有正式稿'


def test_production_lock_blocks_updates_without_touching_draft(batch):
    p, root, doc = batch
    with p._locked(root, doc):
        with pytest.raises(p.ProductionError, match='正在更新'):
            p.start_node(root, 'production.yaml', 'ch051', 'explore_context')
    assert not (root / '正文/51.md').exists()


def test_create_document_empty_chapters_has_explicit_error():
    p = engine()
    with pytest.raises(p.ProductionError, match='章节列表不能为空'):
        p.create_document('空任务', [], host='qoder')


def test_cli_catches_template_validation_valueerror(batch, monkeypatch, capsys):
    p, root, doc = batch
    doc['chapters'][0]['overrides'] = {'explore_context': {'model': 'forbidden'}}
    write_manifest(root, doc)
    monkeypatch.setattr(sys, 'argv', ['production.py', 'status', '--project', str(root)])
    assert p.main() == 2
    assert '生产任务错误' in capsys.readouterr().err
