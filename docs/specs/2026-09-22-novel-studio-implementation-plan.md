# novel-studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打开当前小说工作台，收到真实渲染回执后让 supervisor 等待用户授权。

**Architecture:** skill 编排，标准库启动器管理服务，后端绑定规范项目路径和当前工作流；浏览器按本次 nonce 与文件版本报告 ready。现有 pipeline 仅被读取推导，运行仍由宿主执行。

**Tech Stack:** Python 3.9+ / FastAPI / watchdog / pytest / 原生 JS。

**Spec:** `docs/specs/2026-09-22-novel-studio-skill-design.md`

## Global Constraints

- 不提交 Git，不重置用户改动，不改 demo-novel 的数据。
- 继续已有项目不 scaffold、不 reconcile；UI-ready 不等于执行授权。
- 第二轮外层多章节任务图不在本轮。
- 不新增生产第三方依赖；单项目绑定是后端限制，不只是前端隐藏。

## Task 1: 范围与就绪会话

Files: create `shared/studio_session.py`, `shared/test_studio_server.py`; modify `shared/server.py`。

Interfaces: `StudioScope(project: Optional[Path], workflow: str, chapter: Optional[int])`；`ReadySessions.create(revision, context)`、`get(launch_id, revision)`、`ack(launch_id, revision, current_revision)`。server 全局 scope 固定到进程启动，测试 monkeypatch。

- [ ] 先写隔离与会话失败测试，执行 `python -m pytest shared/test_studio_server.py -q`。

```python
def test_read_only_graph(client, project):
    before = (project / 'pipeline.json').read_bytes()
    assert client.get('/api/graph', params={'project': project.name}).status_code == 200
    assert (project / 'pipeline.json').read_bytes() == before

def test_old_tab_cannot_ack_new_launch(client):
    first = client.post('/api/ui/session').json()
    second = client.post('/api/ui/session').json()
    client.post('/api/ui/ready', json={'launch_id': first['launch_id'], 'revision': first['revision']})
    assert client.get('/api/ui/session/' + second['launch_id']).json()['status'] == 'pending'
```

- [ ] 实现 scope：所有项目解析命中后比较 Path.resolve 相等；子路径用 relative_to；工作流限定根目录 yaml；每次读取验证 DAG 和节点文件 containment。
- [ ] 会话采用 secrets.token_urlsafe，monotonic TTL 600 秒，上限 128；锁保护内存字典，get/ack 检查 revision，过期不返回 ready。
- [ ] 在 static mount 之前接入 health/session/ready/state 路由；绑定 run/create/add 拒绝，WS 过滤范围，启动参数固定 context。
- [ ] 修 GET graph/state 为 derive_status(load_state) 不写盘；watcher 仅投递 graph-changed/status-changed 且监听 rename/delete；增加 shutdown 清理。
- [ ] graph save 使用 revision 比较+load_graph 校验+唯一临时文件+replace，不 reconcile；日志和正文路径采用同一校验。
- [ ] 执行新测试及现有 `python -m pytest shared/ -q`，检查拒绝异项目、路径穿越、前缀 sibling、非法 DAG 与回执 revision 不匹配。

## Task 2: 启动器和薄入口

Files: create `shared/launch_studio.py`, `shared/test_launch_studio.py`, `skills/novel-studio/SKILL.md`, `.qoder/commands/novel-studio/SKILL.md`。

Consumes: Task 1 health 的 service/workspace/project_path/workflow/chapter/studio_protocol 和三个 ui session 接口。
Produces: `python shared/launch_studio.py --project PATH --workflow graph.yaml [--chapter N] [--port 8766] [--timeout 120] [--no-open]`；stdout 最终结构化 JSON，诊断 stderr，退出 0 仅代表 render ready。

- [ ] 测试复用身份必须完整相等；同名异路径、不匹配 workflow/chapter/protocol 不复用。

```python
def test_identity_requires_path():
    from launch_studio import matches_service
    expected = {'workspace': 'D:/nf', 'project_path': 'D:/nf/projects/a', 'workflow': 'graph.yaml', 'chapter': 51}
    other = dict(expected, service='novel-pipeline-studio', studio_protocol=1, project_path='D:/other/a')
    assert not matches_service(other, expected)
```

- [ ] 只读加载并校验图，缺失/非法立即失败；先扫描连续 20 端口寻找匹配实例，再尝试空端口 spawn 当前 sys.executable + server.py，启动日志置系统临时目录，失败清理仅自己子进程。
- [ ] 每次 POST session，URL query launch_id；webbrowser.open 后轮询 GET session，sleep 短且有 monotonic deadline；进程提前退出、拒开浏览器、timeout 非零。输出包含 awaiting_confirmation=true；不自动运行或批准节点。
- [ ] 写 skill：相对自身位置定位 repo，已有配置保留，准备工作流不是改 UI 代码；启动器成功后询问并 STOP；确认后重新读取用户保存的图再运行，人工门再次确认。按需读 novel-runner。Qoder 文件仅指向正典。
- [ ] 运行 `python -m pytest shared/test_launch_studio.py -q`；`--help` 与临时项目实际服务探活，不生成正文。

## Task 3: 浏览器加载屏障与增量刷新

Files: modify `shared/ui/index.html`, `shared/ui/studio.css`, `shared/ui/studio.js`。

Consumes: health/session APIs，graph/state 的 revision/state/host，WS type/project/path/workflow；save API 可传 revision。
Produces: 加载屏障、绑定模式、真实绘制回执、不覆盖用户编辑的增量更新。

- [ ] 先检查节点 DOM、Inspector 保存、WS 分支，保留现有画布和外观，不重建 UI 框架。
- [ ] HTML 初始 loading overlay、layout inert；health 确定绑定 context 后加载 project/workflow/graph，不使用旧 localStorage context；未知 token/错误图不解除屏障。
- [ ] 渲染完成后等待两帧，并检查节点数量与边，再 ack 当前 revision。

```javascript
await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
const response = await fetch('/api/ui/ready', {
  method: 'POST', headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({launch_id: session.launch_id, revision: graphRevision})
});
if (!response.ok) throw new Error('工作流已变化，请刷新后重试');
```

- [ ] 绑定模式隐藏切换/派发/运行/基线校准按钮，保留编辑和阅读；绑定模式 runNode 防御性早退。
- [ ] state 事件调用 `/api/state` 更新指示器/运行标记/边与 Inspector 状态，不能调用 selectNode 重填输入；graph 事件去抖且交互/dirty 时延期；save 带 revision，409 报告冲突而非覆盖。
- [ ] 执行 `node --check shared/ui/studio.js`，浏览器检查加载状态、token ack、编辑保存、状态刷新保留 DOM/草稿。

## Task 4: 集成核验

- [ ] `python -m pytest shared/ -q` 与 `node --check shared/ui/studio.js`。
- [ ] 临时目录创建两小说 fixture，打开指定工作台真实浏览器渲染；启动器退出 0，二次启动复用同服务但生成新 nonce。
- [ ] 请求异项目返回 403；检查 watch/status 事件不会写 pipeline.json；刷新保留进度。
- [ ] 模拟渲染失败/timeout 不返回 ready；检查绑定 run endpoint 拒绝且未产生正文。
- [ ] 独立只读审查与 diff 核对。只报告已实际运行的验证，标记真实宿主新命令加载仍需重新扫描。
