"""父任务绑定、章节下钻与覆盖保存；不启动任何真实小说节点。"""
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient
import production
import server
from test_production import document


@pytest.fixture
def studio(tmp_path, monkeypatch):
    doc = document(production)
    path = tmp_path / 'production.yaml'
    path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding='utf-8')
    monkeypatch.setattr(server, 'studio_scope', SimpleNamespace(project=tmp_path.resolve(), workflow='production.yaml', chapter=None))
    return TestClient(server.app, base_url='http://127.0.0.1'), tmp_path, doc


def test_parent_view_loads_without_mutating_state(studio):
    client, root, _ = studio
    before = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    response = client.get('/api/graph', params={'project': str(root), 'workflow': 'production.yaml'})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['graph']['nodes']['ch051']['kind'] == 'subworkflow'
    assert data['production']['instance'] is None
    assert data['state']['nodes']['ch052']['status'] == 'blocked'
    assert data['currentChapter'] is None
    assert before == {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_drilldown_is_limited_to_bound_task(studio):
    client, root, _ = studio
    params = {'project': str(root), 'workflow': 'production.yaml', 'instance': 'ch052'}
    response = client.get('/api/graph', params=params)
    assert response.status_code == 200, response.text
    assert response.json()['currentChapter'] == 52
    assert response.json()['production']['instance'] == 'ch052'
    assert response.json()['graph']['nodes']['explore_context']['kind'] == 'agent'
    assert client.get('/api/graph', params=dict(params, instance='../other')).status_code == 400
    assert client.get('/api/graph', params=dict(params, workflow='graph.yaml')).status_code == 403


@pytest.mark.parametrize('endpoint', ['/api/graph', '/api/state'])
@pytest.mark.parametrize('instance', [None, 'ch051'])
def test_production_metadata_supplies_navigation_and_saved_supplements(studio, endpoint, instance):
    client, root, doc = studio
    doc['chapters'][0]['overrides'] = {'explore_context': {'prompt_append': '保留本章约束'}}
    (root / 'production.yaml').write_text(yaml.safe_dump(doc, allow_unicode=True), encoding='utf-8')
    params = {'project': str(root), 'workflow': 'production.yaml'}
    if instance:
        params['instance'] = instance
    data = client.get(endpoint, params=params).json()
    chapters = data['production']['chapters']
    assert chapters == doc['chapters']
    assert chapters[0]['id'] == 'ch051'
    assert chapters[0]['params']['chapter_title'] == 'title51'
    assert chapters[0]['overrides']['explore_context']['prompt_append'] == '保留本章约束'
    assert data['state']['production'] == data['production']


def test_raw_graph_save_cannot_replace_production_manifest(studio):
    client, root, _ = studio
    before = (root / 'production.yaml').read_bytes()
    response = client.post('/api/graph/save', json={'project': str(root), 'workflow': 'production.yaml',
                           'graph': {'version': 1, 'nodes': {'bypass': {'kind': 'human', 'inputs': [], 'outputs': []}}}})
    assert response.status_code == 403
    assert (root / 'production.yaml').read_bytes() == before


def test_only_chapter_overrides_can_be_saved(studio):
    client, root, _ = studio
    base = {'project': str(root), 'workflow': 'production.yaml', 'instance': 'ch051'}
    data = client.get('/api/graph', params=base).json()
    body = dict(base, overrides={'explore_context': {'inputs_add': ['facts.txt']}}, revision=data['revision'])
    response = client.post('/api/production/chapter', json=body)
    assert response.status_code == 200, response.text
    assert response.json()['revision'] != data['revision']
    assert client.post('/api/production/chapter', json=body).status_code == 409
    body['revision'] = response.json()['revision']
    body['overrides'] = {'explore_context': {'skills': []}}
    assert client.post('/api/production/chapter', json=body).status_code == 400
    assert client.post('/api/production/chapter', json=dict(body, graph={})).status_code == 422


@pytest.mark.parametrize('endpoint', ['/api/node/start', '/api/node/finish', '/api/node/run'])
def test_legacy_execution_routes_cannot_change_production_state(studio, endpoint):
    client, root, _ = studio
    response = client.post(endpoint, json={'project': str(root), 'workflow': 'production.yaml', 'node_id': 'ch051'})
    assert response.status_code == 403
    assert not (root / 'production_pipeline.json').exists()


def test_launcher_resolves_parent_without_fake_chapter(studio):
    from launch_studio import resolve_context
    _, root, _ = studio
    context = resolve_context(str(root), 'production.yaml')
    assert context['chapter'] is None


def test_parent_ready_handshake_uses_manifest_revision(studio):
    client, root, _ = studio
    session = client.post('/api/ui/session')
    assert session.status_code == 200, session.text
    data = session.json()
    assert data['chapter'] is None
    assert client.post('/api/ui/ready', json={'launch_id': data['launch_id'], 'revision': data['revision']}).status_code == 200


def test_production_reader_cannot_overwrite_old_manuscript(studio):
    client, root, _ = studio
    old = root / 'old.md'
    old.write_text('keep original', encoding='utf-8')
    response = client.post('/api/chapter/save', json={'project': str(root), 'file': 'old.md', 'content': 'replacement'})
    assert response.status_code == 403
    assert old.read_text(encoding='utf-8') == 'keep original'


def test_malformed_manifest_returns_actionable_error(studio):
    client, root, _ = studio
    (root / 'production.yaml').write_text('kind: [broken', encoding='utf-8')
    assert client.get('/api/graph', params={'project': str(root), 'workflow': 'production.yaml'}).status_code == 400


def test_template_reference_cannot_be_detached_via_graph_save(studio, monkeypatch):
    import chapter_templates
    client, root, _ = studio
    monkeypatch.setattr(server, 'studio_scope', SimpleNamespace(project=root, workflow='graph.yaml', chapter=1))
    path = root / 'graph.yaml'
    path.write_text(yaml.safe_dump(chapter_templates.reference()), encoding='utf-8')
    before = path.read_bytes()
    expanded = chapter_templates.instantiate()
    response = client.post('/api/graph/save', json={'project': str(root), 'graph': expanded})
    assert response.status_code == 403
    assert path.read_bytes() == before


def test_production_state_atomic_replace_notifies_bound_workflow(studio, monkeypatch):
    import queue
    from watchdog.events import FileMovedEvent
    _, root, _ = studio
    events = queue.Queue()
    monkeypatch.setattr(server, '_pending_changes', events)
    watcher = server._ProjectFileWatcher()
    watcher._DEBOUNCE_SEC = 0.01
    try:
        state = root / '工作区/生产任务/test-batch/state.json'
        watcher.on_moved(FileMovedEvent(str(state.with_name('tmpfile')), str(state)))
        event = events.get(timeout=2)
        assert event['type'] == 'status-changed'
        assert event['workflow'] == 'production.yaml'
    finally:
        watcher.close()


def test_prompt_is_readonly_and_has_instance_execution_context(studio):
    client, root, _ = studio
    before = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    response = client.post('/api/production/prompt', json={'project': str(root), 'workflow': 'production.yaml',
                           'instance': 'ch051', 'node_id': 'explore_context'})
    assert response.status_code == 200, response.text
    assert '--instance ch051' in response.json()['prompt']
    assert before == {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
