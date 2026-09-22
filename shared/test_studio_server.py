"""单项目工作台：读写边界、可续跑与渲染握手。仅操作临时项目。"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
import server

GRAPH = """version: 1
name: studio-test
params:
  chapter_num: 51
nodes:
  draft:
    kind: agent
    role: writer
    prompt: write
    inputs: []
    outputs: [draft.md]
  approve:
    kind: human
    after: [draft]
    inputs: [draft.md]
    outputs: [final.md]
    ask: review
"""


@pytest.fixture
def studio(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    projects = root / "projects"
    project = projects / "novel"
    other = projects / "novel-other"
    project.mkdir(parents=True)
    other.mkdir()
    for p in (project, other):
        (p / "graph.yaml").write_text(GRAPH, encoding="utf-8")
        (p / "draft.md").write_text("draft", encoding="utf-8")
        (p / "pipeline.json").write_text(json.dumps({
            "version": 1, "params": {"chapter_num": 51},
            "running_node": None,
            "nodes": {"approve": {"ackAt": "2026-09-22T00:00:00Z", "status": "current"}},
        }), encoding="utf-8")
    monkeypatch.setattr(server, "STUDIO_ROOT", root)
    monkeypatch.setattr(server, "PROJECTS_DIR", projects)
    monkeypatch.setattr(server, "CUSTOM_PROJECTS_FILE", root / "custom_projects.json")
    monkeypatch.setattr(server, "load_custom_projects", lambda: [])
    monkeypatch.setattr(server, "studio_scope", SimpleNamespace(
        project=project.resolve(), workflow="graph.yaml", chapter=51), raising=False)
    return TestClient(server.app, base_url='http://127.0.0.1'), project, other


def test_bound_health_and_project_list(studio):
    client, project, _ = studio
    health = client.get('/api/health').json()
    assert health.get('bound_project') == project.name
    assert health['studio_protocol'] == 1
    assert Path(health['project_path']) == project
    assert health['chapter'] == 51
    assert [p['slug'] for p in client.get('/api/projects').json()['projects']] == [project.name]


def test_graph_get_preserves_existing_state_and_default_chapter(studio):
    client, project, _ = studio
    baseline = (project / 'pipeline.json').read_bytes()
    modified = (project / 'pipeline.json').stat().st_mtime_ns
    for endpoint in ('/api/graph', '/api/state', '/api/graph'):
        r = client.get(endpoint, params={'project': project.name})
        assert r.status_code == 200
        assert r.json()['currentChapter'] == 51
        assert r.json()['revision']
    assert (project / 'pipeline.json').read_bytes() == baseline
    assert (project / 'pipeline.json').stat().st_mtime_ns == modified


def test_other_project_read_rejected(studio):
    client, _, other = studio
    for endpoint in ('/api/graph', '/api/chapters', '/api/workflows', '/api/memory'):
        assert client.get(endpoint, params={'project': str(other)}).status_code == 403


def test_render_ack_is_not_reusable(studio):
    client, project, _ = studio
    before = (project / 'pipeline.json').read_bytes()
    a = client.post('/api/ui/session')
    assert a.status_code == 200
    first = a.json()
    second = client.post('/api/ui/session').json()
    assert first['launch_id'] != second['launch_id']
    assert client.post('/api/ui/ready', json={
        'launch_id': first['launch_id'], 'revision': first['revision'],
    }).status_code == 200
    assert client.get('/api/ui/session/' + first['launch_id']).json()['status'] == 'ready'
    assert client.get('/api/ui/session/' + second['launch_id']).json()['status'] == 'pending'
    assert (project / 'pipeline.json').read_bytes() == before


def test_configuration_change_invalidates_ready(studio):
    client, project, _ = studio
    session = client.post('/api/ui/session').json()
    payload = {'launch_id': session['launch_id'], 'revision': session['revision']}
    assert client.post('/api/ui/ready', json=payload).status_code == 200
    (project / 'graph.yaml').write_text(GRAPH.replace('prompt: write', 'prompt: revised'), encoding='utf-8')
    assert client.get('/api/ui/session/' + session['launch_id']).json()['status'] == 'pending'
    assert client.post('/api/ui/ready', json=payload).status_code == 409
    payload['revision'] = client.get('/api/graph', params={'project': project.name}).json()['revision']
    assert client.post('/api/ui/ready', json=payload).status_code == 200
    assert client.get('/api/ui/session/unknown').status_code == 404


@pytest.mark.parametrize('endpoint,payload', [
    ('/api/projects/create', {'slug': 'new'}),
    ('/api/projects/add', {'path': '.'}),
    ('/api/node/run', {'project': 'novel', 'node_id': 'draft'}),
])
def test_bound_mode_cannot_start_or_create(studio, endpoint, payload):
    client, project, _ = studio
    assert client.post(endpoint, json=payload).status_code == 403
    assert not (project / 'final.md').exists()


@pytest.mark.parametrize('endpoint,payload', [
    ('/api/graph/save', {'graph': {}}),
    ('/api/chapter/save', {'file': 'draft.md', 'content': 'changed'}),
    ('/api/node/start', {'node_id': 'draft'}),
    ('/api/node/finish', {'node_id': 'draft'}),
    ('/api/memory/apply', {'chapter_num': 51, 'changes': {}}),
])
def test_other_project_writes_rejected(studio, endpoint, payload):
    client, _, other = studio
    before = {p.name: p.read_bytes() for p in other.iterdir() if p.is_file()}
    assert client.post(endpoint, json=dict(payload, project=str(other))).status_code == 403
    assert before == {p.name: p.read_bytes() for p in other.iterdir() if p.is_file()}


@pytest.mark.parametrize('file', ['../novel-other/draft.md', '../novel-other/graph.yaml'])
def test_file_containment_not_string_prefix(studio, file):
    client, project, _ = studio
    assert client.get('/api/chapter/read', params={'project': project.name, 'file': file}).status_code == 403
    assert client.post('/api/chapter/save', json={'project': project.name, 'file': file, 'content': 'bad'}).status_code == 403


def test_workflow_and_chapter_are_bound(studio):
    client, project, other = studio
    for workflow in ('../novel-other/graph.yaml', str(other / 'graph.yaml'), 'volume_graph.yaml'):
        assert client.get('/api/graph', params={'project': project.name, 'workflow': workflow}).status_code == 403
    assert client.get('/api/graph', params={'project': project.name, 'chapter': 52}).status_code == 403


def test_graph_save_validates_and_detects_conflicts(studio):
    client, project, _ = studio
    graph_path = project / 'graph.yaml'
    before = graph_path.read_bytes()
    data = client.get('/api/graph', params={'project': project.name}).json()
    invalid = dict(data['graph'], nodes={})
    assert client.post('/api/graph/save', json={'project': project.name, 'graph': invalid, 'revision': data['revision']}).status_code == 400
    assert graph_path.read_bytes() == before
    assert client.post('/api/graph/save', json={'project': project.name, 'graph': data['graph'], 'revision': 'old'}).status_code == 409
    assert graph_path.read_bytes() == before
    data['graph']['nodes']['draft']['prompt'] = 'edited'
    saved = client.post('/api/graph/save', json={'project': project.name, 'graph': data['graph'], 'revision': data['revision']})
    assert saved.status_code == 200
    assert saved.json()['revision'] != data['revision']
    assert 'edited' in graph_path.read_text(encoding='utf-8')


def test_cross_origin_bound_write_rejected(studio):
    client, project, _ = studio
    r = client.post('/api/chapter/save', headers={'Origin': 'https://untrusted.example'}, json={
        'project': project.name, 'file': 'draft.md', 'content': 'bad'})
    assert r.status_code == 403
    assert (project / 'draft.md').read_text(encoding='utf-8') == 'draft'


def test_unbound_legacy_lists_all_projects(studio, monkeypatch):
    client, project, other = studio
    monkeypatch.setattr(server, 'studio_scope', SimpleNamespace(project=None, workflow='graph.yaml', chapter=None))
    assert len(client.get('/api/projects').json()['projects']) == 2
    assert client.get('/api/graph', params={'project': other.name}).status_code == 200


def test_ready_sessions_expire_and_have_a_size_limit():
    from studio_session import ReadySessions
    now = [0.0]
    sessions = ReadySessions(ttl=10, capacity=2, clock=lambda: now[0])
    a = sessions.create('r1', {'project': 'novel'})
    sessions.ack(a['launch_id'], 'r1', 'r1')
    assert sessions.get(a['launch_id'], 'r1')['status'] == 'ready'
    assert sessions.get(a['launch_id'], 'r2')['status'] == 'pending'
    sessions.create('r1', {})
    sessions.create('r1', {})
    with pytest.raises(KeyError):
        sessions.get(a['launch_id'], 'r1')
    b = sessions.create('r1', {})
    now[0] = 11.0
    with pytest.raises(KeyError):
        sessions.get(b['launch_id'], 'r1')


def test_watcher_notifies_without_writing_and_handles_atomic_move(studio, monkeypatch):
    import queue
    from watchdog.events import FileMovedEvent, FileDeletedEvent
    _, project, other = studio
    events = queue.Queue()
    monkeypatch.setattr(server, '_pending_changes', events)
    before = (project / 'pipeline.json').read_bytes()
    watcher = server._ProjectFileWatcher()
    watcher._DEBOUNCE_SEC = 0.01
    try:
        watcher.on_moved(FileMovedEvent(str(project / '.graph.tmp'), str(project / 'graph.yaml')))
        event = events.get(timeout=2)
        assert event['type'] == 'graph-changed'
        assert event['workflow'] == 'graph.yaml'
        watcher.on_deleted(FileDeletedEvent(str(project / 'draft.md')))
        assert events.get(timeout=2)['type'] == 'status-changed'
        watcher._handle(str(other / 'graph.yaml'))
        with pytest.raises(queue.Empty):
            events.get(timeout=0.05)
        assert (project / 'pipeline.json').read_bytes() == before
    finally:
        watcher.close()


def test_broadcast_filters_foreign_project(studio):
    import asyncio
    _, project, other = studio
    messages = []
    class Socket:
        async def send_text(self, data):
            messages.append(json.loads(data))
    manager = server.LiveConnectionManager()
    manager._connections.append(Socket())
    asyncio.run(manager.broadcast({'type': 'status-changed', 'path': str(other), 'workflow': 'graph.yaml'}))
    assert not messages
    asyncio.run(manager.broadcast({'type': 'status-changed', 'path': str(project), 'workflow': 'graph.yaml'}))
    assert len(messages) == 1


def test_websocket_rejects_foreign_origin(studio):
    from starlette.websockets import WebSocketDisconnect
    client, _, _ = studio
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/ws/live', headers={'origin': 'https://untrusted.example'}):
            pass


def test_read_memory_does_not_create_project_files(studio):
    client, project, _ = studio
    before = set(project.rglob('*'))
    assert client.get('/api/memory', params={'project': project.name}).status_code == 200
    assert set(project.rglob('*')) == before


def test_chapter_save_cannot_bypass_graph_validation(studio):
    client, project, _ = studio
    before = (project / 'graph.yaml').read_bytes()
    assert client.post('/api/chapter/save', json={
        'project': project.name, 'file': 'graph.yaml', 'content': 'bad'}).status_code == 403
    assert (project / 'graph.yaml').read_bytes() == before


def test_scope_configuration_reads_default_chapter(studio, monkeypatch):
    _, project, _ = studio
    monkeypatch.setattr(server, 'studio_scope', server.StudioScope())
    server.configure_scope(str(project), 'graph.yaml', None)
    assert server.studio_scope.project == project
    assert server.studio_scope.chapter == 51


def test_ledger_symlink_cannot_escape_project(studio):
    client, project, other = studio
    try:
        (project / '设定').symlink_to(other, target_is_directory=True)
    except OSError:
        pytest.skip('系统未授权创建符号链接')
    before = set(other.rglob('*'))
    assert client.get('/api/memory', params={'project': project.name}).status_code == 403
    assert client.post('/api/memory/apply', json={'project': project.name, 'chapter_num': 51, 'changes': {}}).status_code == 403
    assert set(other.rglob('*')) == before


def test_nested_internal_symlink_cannot_hide_external_ledger(studio):
    client, project, other = studio
    (project / 'cache').mkdir()
    (project / '设定').mkdir()
    target = other / 'snapshot.json'
    target.write_text('{"version": 77}', encoding='utf-8')
    try:
        (project / '设定' / '事实账本').symlink_to(project / 'cache', target_is_directory=True)
        (project / 'cache' / 'snapshot.json').symlink_to(target)
    except OSError:
        pytest.skip('系统未授权创建符号链接')
    before = target.read_bytes()
    assert client.get('/api/memory', params={'project': project.name}).status_code == 403
    assert client.post('/api/memory/apply', json={'project': project.name, 'chapter_num': 51, 'changes': {}}).status_code == 403
    assert target.read_bytes() == before


def test_bound_host_must_be_loopback(studio):
    client, project, _ = studio
    headers = {'Host': 'attacker.test:8766', 'Origin': 'http://attacker.test:8766'}
    assert client.post('/api/chapter/save', headers=headers, json={
        'project': project.name, 'file': 'draft.md', 'content': 'bad'}).status_code == 403
    assert (project / 'draft.md').read_text(encoding='utf-8') == 'draft'
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/ws/live', headers=headers):
            pass


def test_chapters_cannot_list_symlinked_foreign_directory(studio):
    client, project, other = studio
    (other / 'ch999.md').write_text('private', encoding='utf-8')
    try:
        (project / 'chapters').symlink_to(other, target_is_directory=True)
    except OSError:
        pytest.skip('系统未授权创建符号链接')
    assert client.get('/api/chapters', params={'project': project.name}).status_code == 403


def test_internal_graph_link_keeps_logical_workflow_identity(studio):
    client, project, _ = studio
    (project / 'graph.yaml').rename(project / 'actual.yaml')
    try:
        (project / 'graph.yaml').symlink_to(project / 'actual.yaml')
    except OSError:
        pytest.skip('系统未授权创建符号链接')
    data = client.get('/api/graph', params={'project': project.name}).json()
    assert data['workflow'] == 'graph.yaml'
    (project / 'draft.md').unlink()  # 未完成节点才会保留 running 标记。
    assert client.post('/api/node/start', json={'project': project.name, 'node_id': 'draft'}).status_code == 200
    state = json.loads((project / 'pipeline.json').read_text(encoding='utf-8'))
    assert state['running_node'] == 'draft'
    assert not (project / 'actual_pipeline.json').exists()


def test_bound_default_preserves_custom_chapter_padding(studio):
    client, project, _ = studio
    (project / 'graph.yaml').write_text(GRAPH.replace('chapter_num: 51', 'chapter_num: 51\n  chapter_pad: "051"'), encoding='utf-8')
    assert client.get('/api/graph', params={'project': project.name}).json()['graph']['params']['chapter_pad'] == '051'
