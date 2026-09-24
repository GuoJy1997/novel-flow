"""只读核验四章准备结果，不生成状态或正文。"""
from pathlib import Path
import hashlib
import json
import sys
import time

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'shared'))
import production
project = Path('D:/桃园密码')
started = time.monotonic()
workflow = 'interlude-production.yaml'
doc = production.load_document(project, workflow)
graph, state, revision = production.snapshot(project, workflow)
assert list(graph['nodes']) == ['ch051', 'ch052', 'ch053', 'ch054']
assert [state['nodes'][cid]['status'] for cid in graph['nodes']] == ['pending', 'blocked', 'blocked', 'blocked']
models = None
for cid in graph['nodes']:
    child, child_state, child_revision = production.snapshot(project, workflow, cid)
    assert child_revision == revision
    assert len(child['nodes']) == 10
    assert all(e['attempt_count'] == 0 for e in child_state['nodes'].values())
    assert child_state['binding_drift'] is None, child_state['binding_drift']
    this_models = {nid: entry['model'] for nid, entry in child_state['nodes'].items() if entry['kind'] == 'agent'}
    assert all(this_models.values())
    if models is not None:
        assert this_models == models
    models = this_models
    for node in child['nodes'].values():
        assert 'model' not in node
    assert all(not entry['actual_model'] for entry in child_state['nodes'].values())
baseline = json.loads((root / '.qoder/interlude-baseline.json').read_text(encoding='utf-8'))
changed = [rel for rel, digest in baseline.items()
           if not (project / rel).is_file() or hashlib.sha256((project / rel).read_bytes()).hexdigest() != digest]
assert changed == [], changed
assert not (project / '工作区/生产任务' / doc['id'] / 'state.json').exists()
print(json.dumps({'chapters': list(graph['nodes']), 'status': [v['status'] for v in state['nodes'].values()],
                  'template_hash': doc['template']['hash'], 'planned_models': models,
                  'actual_dispatch_verified': False, 'old_files_unchanged': len(baseline),
                  'elapsed_seconds': round(time.monotonic() - started, 2)}, ensure_ascii=False))
