# novel-studio 单项目工作台设计

状态：用户已批准第一轮设计并授权实施。第二轮外层多章节任务图不在本轮；不提交 Git。

## 目标与边界

项目仍是项目，skill 只是面向宿主 supervisor 的薄入口。保留现有 Python 引擎、小说目录和专家技能；不把专家提示词、代码或历史塞进 SKILL.md。支持 Qoder 与 Antigravity，当前实际宿主决定模型。Flash/Pro 不作为跨代模型质量排名。

流程：确定项目和本次工作流 → 按需求准备节点/提示词/技能/参数 → 只读校验 → 启动或复用该项目服务 → 打开页面且等待真实渲染回执 → supervisor 在主对话询问“可以开始跑工作流了吗？”并结束本轮回复 → 用户明确确认后才执行节点。

网页允许加载壳，但工作台在图谱渲染成功前不可见、不可交互；不可能在浏览器加载之前完成浏览器渲染。加载失败保留错误遮罩，不谎报就绪。UI-ready 不等于执行授权。没有执行/启动按钮桥；绑定模式禁用 UI 执行入口，人工门同样由主对话确认。

## 三层职责

- `skills/novel-studio/SKILL.md`：流程和安全边界，按需读取 novel-runner；Qoder 项目命令放 `.qoder/commands/novel-studio/SKILL.md` 作薄指针。
- `shared/launch_studio.py`：标准库启动器，校验服务身份、分配端口、开浏览器、等待本次回执。`shared/server.py` 继续提供数据与静态界面。`shared/studio_session.py` 单独承载工作台范围与短期就绪会话。
- `projects/<project>/` 或显式外部小说目录：保留配置、素材、状态。继续已有项目不 scaffold、不 reconcile、不自动注册改写 agent 文件、不运行任何节点。

## 后端范围与接口

新增 `server.py --project <slug-or-path> --workflow graph.yaml [--chapter N]`。工作流和章节是一次服务实例的上下文，默认章节来自已准备的图配置；绑定模式不提供项目/工作流/章节切换。旧无参多项目入口保留。

健康检查包含 service、workspace、bound_project、project_path、workflow、chapter、studio_protocol=1。复用必须同时匹配真实工作区、规范化项目路径、工作流、章节与协议；同名项目不等价。异项目/无绑定旧实例/非本服务占用端口时顺延，不杀进程。

所有项目读写接口统一经过规范路径范围校验。不能只隐藏前端选项；禁止异项目路径、工作流跳目录、文件路径前缀混淆与符号链接越界。绑定模式禁止创建/关联项目及 `/api/node/run`，日志访问也检查归属。WS 和文件监听只触达绑定项目。跨站请求不得利用绑定实例执行写操作。

新增接口：

- `POST /api/ui/session` → `{launch_id, revision, project, project_path, workflow, chapter, status:'pending'}`。每次启动新 nonce，短期有效，仅内存保存。
- `GET /api/ui/session/{launch_id}` → 同一结构，若 UI 回执的 revision 等于当前图谱 revision 才为 ready。
- `POST /api/ui/ready` 输入 `{launch_id, revision}`；未知/过期 nonce 拒绝，配置已变更返回 409，成功状态 ready。只表示页面完成图谱绘制，不写运行授权或 pipeline.json。
- `GET /api/graph` 与 `GET /api/state` 只读推导；响应有 revision（原始 graph 内容 SHA256），不写状态文件。`/api/state` 返回 state/host/revision/currentChapter/currentVolume，不发送整图。
- `POST /api/graph/save` 先验证合法 DAG，再原子保存；支持 revision 乐观并发检查防止覆盖宿主更新；返回最新 revision/state。校验失败不破坏旧文件。

启动器返回 JSON：`status:'ready', awaiting_confirmation:true, url, launch_id, revision, reused` 及工作区/项目/工作流/章节身份；只有本次 UI 回执才退出 0。开浏览器失败、依赖缺失、就绪超时或启动失败均返回非零及可读错误。`--no-open` 供测试或宿主有浏览器工具时使用，仍等待真实回执，不可跳过。

## 前端与刷新

初始 loading 遮罩和 inert 工作台；读取健康信息后绑定当前项目，不沿用 localStorage 的另一项目/工作流。从 `?launch_id=` 校验本次 session，加载技能与 graph，绘制节点和连线，等待浏览器绘制帧后 POST ready，成功才解锁。直接打开绑定服务时也创建独立 session。

绑定模式隐藏项目、工作流和章节切换器、运行/派发/基线重置按钮；保留提示词、技能、依赖和文件编辑。新增模型可选覆写不在本轮，避免误以为编辑 model 就覆盖角色绑定。

事件协议：`graph-changed`（图结构或参数变化）、`status-changed`（pipeline 状态或素材变化），带 project/path/workflow。监听器不重算写盘，仅通知；支持原子 rename/move/delete。GET 纯读，从根上消除读→写→watcher→读循环。

状态更新只更新状态指示和运行标记，不销毁卡片、输入框或未保存内容。图变化整图刷新；用户编辑/拖拽期间暂缓刷新，保存有 revision 冲突提示，不能默默覆盖。刷新错误可重试且不报 ready。

## 验收

Python 3.9+，前端原生 JS，不新增生产第三方依赖。测试使用临时小说目录，不写 demo-novel。覆盖所有隔离入口、文件边界、纯读不变基线、人工确认保留、非法图保护、状态/图事件分类、会话过期和版本不匹配、同项目复用/异项目换端口、旧回执不可复用、启动失败/超时。浏览器验收遮罩、图渲染、真实回执、编辑保存、状态更新不夺输入焦点和跨项目拒绝。模型实际子代理路由不在本轮；不声称单元测试证明模型执行归属。
