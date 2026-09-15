# 工业化小说生产系统技术架构白皮书
*(Open Source Novel Production Architecture & Specification Guide)*

---

## 一、 系统架构全景

本系统面向长篇连载与深度小说创作，采用分层清晰的四层架构：

```mermaid
flowchart TB
    subgraph Host_Layer["1. 宿主 Agent 交互层 (IDE & Webview Extension)"]
        A1["Antigravity / Cursor / VS Code / Qoder 侧边栏"]
        A2["独立 Web 浏览器端 (http://127.0.0.1:8766)"]
    end

    subgraph Studio_Layer["2. 可视化调度层 (Node-Graph Studio)"]
        B1["SVG 响应式节点拓扑画布 (缩放/拖拽连线/一键剪线)"]
        B2["属性检查器 Inspector (Role/Prompt/输入输出/Assert 实时调节)"]
        B3["实时终端抽屉 (SSE 零延迟日志推流)"]
        B4["小说成果阅读器 (原稿/润色稿/审查报告双栏审阅)"]
    end

    subgraph Engine_Layer["3. 核心流水线引擎 (Pipeline Core Engine)"]
        C1["DAG 拓扑调度器与循环门禁解析 (pipeline.py)"]
        C2["增量状态机与 SHA256 变动探测 (hash_path / derive_status)"]
        C3["质量硬断言器 (evaluate_asserts: 字数区间 / 格式 / SCORES)"]
        C4["FastAPI 进程与静态 UI 托管 (server.py)"]
    end

    subgraph Storage_Layer["4. 文件即数据存储层 (Novel Workspaces)"]
        D1["graph.yaml (声明式拓扑定义与执行参数)"]
        D2["world.md / relations.md / outline.md (设定与骨架)"]
        D3["drafts/ / chapters/ / workflow/ (各阶段演进文稿)"]
        D4["pipeline.json (单一写者状态快照)"]
    end

    Host_Layer --> Studio_Layer
    Studio_Layer <--> Engine_Layer
    Engine_Layer <--> Storage_Layer
```

---

## 二、 核心设计概念与运行机制

### 1. 三阶异构节点模型 (Three Node Kinds)
- **`agent`（大模型智能体节点）**：
  - 负责高智力创作环节（状态提炼、正文起草、去 AI 味盲审、多维审查打分）；
  - 拥有明确的角色设定（`role`）、核心指令（`prompt`）、绑定技能（`skills`）以及**质量硬断言（`assert`）**；
  - 由宿主 Agent（如 Antigravity）直接免密消费并落盘。
- **`command`（本地命令行节点）**：
  - 负责确定性本地任务（如执行 `novel_stats.py` 计算全书字数、伏笔台账提取）；
  - 0-Token 成本，100% 确定性，由本地 Python 运行时驱动。
- **`human`（人机协同关键放行闸门）**：
  - 例如正文入库、关键剧情分支选择；
  - 记录 `ackAt` 确认时间戳，只要上游输入文稿发生任何变动，审批即刻自动作废，必须重新确认。

---

### 2. 增量状态机与 SHA256 物理指纹 (Incremental Hashing)
- 系统的 `pipeline.py` 不依赖不可靠的操作系统文件修改时间（`mtime`），而是对每个节点的所有输入文件内容计算 SHA256 哈希；
- 目录按内部排序后的文件相对路径 + 各文件内容哈希复合计算；
- 当上游未变时，该节点状态为 `current`；点击“执行”时秒级跳过；
- 只有输入发生变动的节点以及受其影响的下游节点会自动变为 `stale`（过期），做到修改哪里重跑哪里。

---

### 3. 严格物理级上下文隔离 (Strict Context Isolation by Design)
- **零聊天记录共享**：节点之间绝不共享杂乱的 Chat 历史，避免超长 Token 爆炸和注意力漂移；
- **文件即唯一接口**：节点仅读取 `inputs` 中显式声明的文件，产物写入 `outputs`；
- **对抗式审查设计**：写作者与审查者角色对立，审查报告定位具体句段并输出结构化评分 `SCORES: {"overall": 85}`。

---

### 4. 质量硬断言 (Asserts Enforcement)
`pipeline.py` 在状态推导时自动对产出文件进行多维断言评估：
- `min_words` / `max_words`：中文字符数下限与上限校验；
- `min_score` / `score_field`：评分门禁，低于门槛直接判定为 `failed` 阻止流转；
- `contains_markers`：强制检查关键伏笔标记是否存在。

---

## 三、 核心运行机制流转图解

### 1. 全流程长篇小说工业化生产闭环机制

```mermaid
flowchart TD
    subgraph Phase_0["阶段 0：需求澄清与最高宪法立项 (Clarify & Genesis)"]
        A1["创作者灵感 / 商业题材需求"] --> A2["六阶递进问询引导 (novel_clarify)"]
        A2 --> A3["《小说项目最高宪法》(novel.md)"]
        A3 --> A4["原子化设定与大纲库\n(世界观/ 人物/ 大纲/ 资产/ 事实账本)"]
        A3 --> A5["声明式流水线拓扑 (graph.yaml)"]
    end

    subgraph Phase_1["阶段 1：单章正文流水线生产 (Chapter Pipeline)"]
        A4 & A5 --> B1["1. 上下文蒸馏 (gather_context)\n提炼本章看点、核心矛盾、前置物理状态"]
        B1 --> B2["2. 主笔撰写初稿 (draft_chapter)\n严格受限视角(Close Third POV)、推剧情、防剧透"]
        B2 --> B3["3. 语言声纹去AI味润色 (deai_polish)\n对标 voice_sample.md 声纹，剔除模板排比与禁词"]
        B3 --> B4["4. 对抗式盲审质检 (review_qc)\nOOC/战力/伏笔多维审查，输出 SCORES 评分"]
    end

    subgraph Phase_2["阶段 2：质量门禁与人机协同 (Gate & Human Review)"]
        B4 --> C1{"硬断言门禁\nevaluate_asserts\n(字数区间 / 评分及格线)"}
        C1 -- "未达标 (failed)" --> C2["阻断流转 / 触发双向仲裁与修改"]
        C2 -.-> B2
        C1 -- "达标" --> C3["5. 作者人工放行 (author_accept)\n双栏比对正文与质检报告，一键签发入库"]
    end

    subgraph Phase_3["阶段 3：正文归档与事实记忆沉淀 (Finalize & Memory Sink)"]
        C3 --> D1["正文正式归档入库 (chapters/ch_XX.md)"]
        D1 --> D2["0-Token 本地统计分析 (novel_stats.py)\n有效字数 / 对话占比 / 伏笔 / 词频分析"]
        D1 --> D3["事实账本与记忆沉淀 (memory_engine.py)\n提取实体变迁、角色已知/未知、伏笔回收状态"]
        D3 --> D4["设定/事实账本/snapshot.json\n(全书最新物理事实基线)"]
        D4 -.->|"作为第 N+1 章前置输入"| B1
    end
```

### 2. 增量 SHA-256 递归状态机流转机制

```mermaid
flowchart TD
    subgraph Trigger["变动探测 (Hash Comparison)"]
        T1["上游输入文件/目录变动\n(递归计算 SHA-256 内容哈希)"] --> T2{"当前哈希 == pipeline.json 记录?"}
        T2 -- "一致 (无修改)" --> S_CURRENT["🟢 current (最新就绪)\n毫秒级增量跳过，不消耗额外算力与Token"]
        T2 -- "不一致 (上游改动 / 产物缺失)" --> S_STALE["🟡 stale (待执行/过期)"]
    end

    subgraph Execution["节点执行与生命周期"]
        S_STALE --> S_RUNNING["🔵 running (执行中)\nAgent 消费 Prompt / Command 运行脚本"]
        S_RUNNING --> S_OUTPUT["产物落盘写入 outputs 指定物理文件"]
        S_OUTPUT --> S_ASSERT{"断言求值 (evaluate_asserts)\n字数区间 / SCORES 门槛 / 必含标记"}
        S_ASSERT -- "全部满足" --> S_PASS["记录最新 Hash 并更新 pipeline.json"]
        S_PASS --> S_CURRENT
        S_ASSERT -- "不达标" --> S_FAIL["🔴 failed (门禁阻断)\n下游节点保持 blocked，等待修正"]
    end
```

### 3. 跨章事实账本与知情边界守卫机制

```mermaid
flowchart LR
    subgraph Chapter_Input["第 N 章生产产物"]
        TXT["正式正文文稿\nchapters/ch_0N.md"]
        QC["盲审质检报告\nworkflow/review_ch_N.md"]
    end

    subgraph Memory_Engine["事实账本与记忆引擎 (memory_engine.py)"]
        EXTRACT["增量事实提取器\n- 实体演化 (伤势/状态/修为/装备)\n- 伏笔台账 (埋设/推进/回收)\n- 关系转变 (结盟/背叛/认知)"]
        LEDGER["全书中央最新事实快照\n设定/事实账本/snapshot.json"]
        HISTORY["历史章节可回溯快照\n设定/事实账本/history/snapshot_ch00N.json"]
    end

    subgraph Chapter_Next["第 N+1 章生产防线 (防吃书 / 防早泄)"]
        BOUNDARY["知情边界守卫\n- 严禁角色知晓未获知的情报\n- 严禁全知上帝视角对白"]
        LORE_GUARD["世界观法则与战力天花板守卫\n- 严禁突破物理常数与设定法则"]
        CLUE_GUARD["伏笔暗线生命周期守卫\n- 未到回收章节严禁提前剧透"]
    end

    TXT & QC --> EXTRACT
    EXTRACT --> LEDGER
    EXTRACT --> HISTORY
    LEDGER --> BOUNDARY & LORE_GUARD & CLUE_GUARD
```

### 4. 吃书冲突排查与双向仲裁决策机制

```mermaid
flowchart TD
    CONFLICT["质检节点报警 / 门禁未通过 / 发现设定冲突"] --> JUDGE{"智能体 / 创作者仲裁冲突属性"}
    
    JUDGE -- "分支 A：正文笔误 / 偶发 OOC / 违规禁词" --> ACTION_A["正文微调方案 (Draft Patch)\n1. 定位章节工作区草稿具体段落\n2. 精准修补正文行文偏差\n3. 重新执行质检节点验证"]
    
    JUDGE -- "分支 B：剧情合理演进 / 新势力突破 / 设定升阶" --> ACTION_B["设定演进回写 (Lore Evolution)\n1. 更新 设定/世界观/ 或 设定/人物/ 档案\n2. 记录突破契机并同步更新事实账本\n3. 刷新全书设定基线，保持后续一致"]
    
    ACTION_A --> RE_EVAL["触发增量状态机推导 (pipeline.py derive_status)"]
    ACTION_B --> RE_EVAL
    RE_EVAL --> DONE["断言达标，节点恢复 🟢 current，流水线解除阻塞"]
```
