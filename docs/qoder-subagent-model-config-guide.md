# 在 Qoder 中给子智能体正确配置模型：宿主驱动式绑定实践指南

> **面向对象**：任何要在 Qoder 里跑「多角色子智能体工作流」的项目（流水线、生产线、评审链等），不限于 novelFlow。
> **经验来源**：novelFlow 小说流水线 2026-09-21 ~ 09-24 的实测与两次返工——先做「全局默认 + Qoder 覆盖层」，被否定后重构为**纯宿主驱动**，shared 测试 61 passed。
> **配套参考**：[qoder-model-routing.md](./qoder-model-routing.md)（Qoder 模型 ID 形态与本地日志位置的原始实测记录）。本文讲**怎么设计**，那篇讲**实测到什么**。

---

## 0. 一句话结论

在 Qoder 里，**「配了模型」和「用上了模型」是两件事**：模型名写错不报错、静默回落；模型在注册时钉死、派发时无法覆盖；改完是否生效时机不定。所以正确的做法不是「把模型名写对」，而是搭一条**能证明模型被用对**的链路：

```
工作流文件只写档位抽象(flash/pro) → 宿主档案给具体模型ID → 解析链产出唯一答案(或明确"未配置")
   → 宿主 Agent 落盘注册 → 真实派发一次 → 核对 resolvedModel
```

novelFlow 的核心设计原则一句话：**模型的唯一来源是「感知到的宿主」，没有哪个宿主是出厂默认。**

---

## 1. 先认清 Qoder 的五个硬约束（全部实测）

| # | 约束 | 实测表现 | 对你的设计意味着什么 |
|---|---|---|---|
| 1 | **无效模型 ID 静默回落** | frontmatter `model:` 写了 Qoder 不认识的串（如 `kimi-k3`、`gemini-3.1-pro-high`），**不报错**，回落到当前会话默认模型；回落目标是**实时**的（同会话先后见过 `gfmodel` 和 `qmodel_38max`） | 这是最危险的坑。任何「靠肉眼检查配置」的方案都不可靠，**必须有派发后的验证闭环** |
| 2 | **模型在注册时钉死** | 当前 Qoder CLI 的 `Agent` 派发工具**不暴露 `model` 参数**（参数只有 `subagent_type` / `prompt` / `description` 等），模型只由定义文件 frontmatter 决定 | 别设计成「调用时临时换模型」。要换模型 = 改配置 + 重新注册 + 新会话。⚠ 早期 videoProduction 文档记录过「派发显式带 model 参数可单次覆盖」，与当前运行时矛盾（疑为版本差异），**一律按「钉死」设计**，不要依赖按调用覆盖 |
| 3 | **重载时机不确定** | 同会话 A/B 双探针：一次外部修改**改变了**后续派发结果，另一次 4 连改对 3 次派发**全无影响**；新增/改名的 agent 类型明确需要新会话 | 改完**不要假定生效、也不要假定不生效**，只能靠真实派发核对。新开会话最稳 |
| 4 | **ID 有三种形态，只认两种** | 内置系统 ID（`qfmodel`）✅、BYOK 裸 UUID（`e1584866-…`，不带 `byok:` 前缀）✅、上游 slug（`kimi-k3` / `gemini-*` / `claude-*`）❌ 静默回落 | 配置里的模型名必须来自**已核实**的 ID 清单，不能从别的项目/别家宿主的文档里抄 |
| 5 | **BYOK UUID 是账号资产** | UUID 属于当前账号的自定义渠道，换账号/删渠道即失效 | 能用内置 ID 就用内置 ID；用 BYOK 必须在文档里记录「失效时去哪重新核对」 |

补充一条边界：Qoder 的 agent 定义文件有两处——**用户级** `~/.qoder/agents/*.md`（全项目共享）与**项目级** `<项目>/.qoder/agents/*.md`（仅本项目）。重名时的优先级未系统实测，**建议一个项目只用一处**，避免多会话并发改同名文件互相覆盖（novelFlow 真出过这个事故，见 §6）。

---

## 2. 核心原则：宿主是模型的唯一来源

### 2.1 反面教材（novelFlow 走过的弯路）

第一版设计是「Antigravity 的 gemini/claude 名当全局默认，再叠一层 qoder 映射覆盖」。看起来省事，实际有三个致命问题：

1. **静默降级**：某节点忘了配 qoder 覆盖，就会带着 gemini 的名字派发到 Qoder → 不报错 → 回落到会话默认模型 → 你以为在跑 Pro，实际在跑 Flash。
2. **启发式猜档位会猜错**：第一版有个 `infer_tier_from_model`，按模型名里有没有 "flash" 猜档位。结果 `review_qc`（本该 Pro 的盲审门禁）因为 graph.yaml 里写了 `gemini-3.8-flash-high`、又没写 `subagent_type`，被推断成 flash **静默降级**。三道质量门禁之一形同虚设。
3. **改一处漏三处**：模型名散落在 graph.yaml、yaml 规格、预设、覆盖表里，换宿主要改四个地方。

用户明确否定这种「缝缝补补」，于是有了第二版。

### 2.2 正面设计

三条规则，缺一不可：

1. **工作流文件里不写任何具体模型名**。角色规格（yaml）和工作流图（graph）只写 `default_tier: flash|pro` 这个**跨宿主抽象**。
2. **具体模型名只存在于 `host_profiles.<host>`**，且各宿主**完全对等**——qoder 和 antigravity 都各自给出全套角色绑定，没有谁是默认。
3. **解析不出结果时返回 `None` 并明确报「未配置」**，绝不回落到别家宿主的模型名，也绝不按名字猜。

收益：换宿主零改动工作流文件；不可能静默降级（要么解析出本宿主的合法 ID，要么明确报错）；换模型只改一处。

---

## 3. 最小可搬架构：三层 + 一条解析链

不需要照抄 novelFlow 的代码量。下面是一个**可以直接搬进任何项目**的精简版。

### 3.1 Layer 1：角色规格（宿主无关）

每个子智能体一个定义，**不含模型名**：

```yaml
# subagents/reviewer.yaml
name: doc_reviewer
description: 文档质量盲审员
role: reviewer
model_config:
  default_tier: pro          # 只写档位，这是唯一的跨宿主抽象
tools:
  enable_write_tools: false
  enable_mcp_tools: false
system_prompt: |
  你是一名严格的文档盲审员……
```

### 3.2 Layer 2：宿主档案（具体模型的唯一出处）

```jsonc
// manifest.json → host_profiles
{
  "qoder": {
    "tiers": {                          // 档位 → 候选模型（取第一个）
      "flash": ["qfmodel"],
      "pro":   ["qmodel_38max"]
    },
    "role_models": {                    // 角色 → 模型（权威，优先于 tiers）
      "doc_writer":  "qfmodel",
      "doc_reviewer": "qmodel_38max"
    },
    "registration": {                   // 注册契约：告诉宿主 Agent 怎么落盘
      "mechanism": "host-agent-writes-definition-files",
      "agent_dir": ".qoder/agents/",
      "file_pattern": "{name}.md",
      "frontmatter_fields": ["name", "description", "model", "tools"],
      "model_field": "model",
      "body": "yaml 规格的 system_prompt 原文",
      "dispatch_tool": "Agent(subagent_type=<name>)",
      "per_call_model_override": false,
      "requires_new_session": true,
      "verify_with": "~/.qoder/projects/<项目slug>/<会话id>/subagents/task-*.json 的 resolvedModel 字段"
    }
  },
  "antigravity": { "...": "与 qoder 对等，同样给全套 role_models + tiers" },
  "generic":     { "role_models": {}, "description": "未知宿主兜底：不提供任何映射，解析结果为『未配置』" }
}
```

**`role_models` 与 `tiers` 的分工**：`tiers` 是「新角色没单独指定时的兜底」，`role_models` 是「这个角色在这个宿主下就用这个模型」的权威声明。两者可以不一致——novelFlow 的 `deai_polisher` 的 `default_tier` 是 `flash`（给 antigravity 用），但 `qoder.role_models` 把它提到了 `qmodel_38max`。**这是特性不是 bug**：正因为 Qoder 不支持按调用覆盖，注册时正好可以一次配好各司其职。

### 3.3 Layer 3：解析链（可直接抄的实现）

```python
def resolve_node_model(node, host, profiles, spec_default_tier=None):
    """解析一个工作流节点在当前宿主下实际使用的模型。
    任何情况都不回落到别家宿主的模型名；解析不出就返回 None。"""
    raw_model = (node.get("model") or "").strip() or None
    raw_tier  = (node.get("model_tier") or "").strip() or None
    raw_role  = (node.get("subagent_type") or "").strip() or None

    profile = profiles.get((host or "").lower())
    if profile is None:                                   # ⑤ 未识别宿主
        return {"model": None, "origin": "no-host"}

    tiers, role_models = profile.get("tiers") or {}, profile.get("role_models") or {}
    if not tiers and not role_models:                     # 空档案 = 未配置
        return {"model": None, "origin": "host-unmapped"}

    known = {m for ms in tiers.values() for m in ms} | {m for m in role_models.values() if m}

    bound = role_models.get(raw_role) if raw_role else None
    if bound:                                             # ① 角色绑定（权威）
        return {"model": bound, "origin": "role-mapped"}  #    图谱里遗留的 model 名一律忽略
    if raw_model and raw_model in known:                  # ② 显式且宿主认识（逃生舱）
        return {"model": raw_model, "origin": "explicit-matched"}
    tier = raw_tier or spec_default_tier
    mapped = (tiers.get((tier or "").lower()) or [None])[0]
    if mapped:                                            # ③ 档位映射
        return {"model": mapped, "tier": tier, "origin": "tier-mapped"}
    return {"model": None, "tier": tier, "origin": "host-unmapped"}   # ④ 宿主有档案但没覆盖
```

宿主感知本身很简单，两种手段叠加即可：

```python
HOST_FINGERPRINTS = [("QODER", "qoder"), ("ANTIGRAVITY", "antigravity")]   # 环境变量名前缀
HOST_OVERRIDE_ENV = "MYPROJECT_HOST"                                       # 人工强制指定

def detect_host(env=os.environ):
    forced = env.get(HOST_OVERRIDE_ENV, "").strip().lower()
    if forced:
        return forced
    for prefix, key in HOST_FINGERPRINTS:
        if any(n.upper().startswith(prefix) for n in env):
            return key
    return None
```

### 3.4 五种解析结果，只有三种是「配好了」

| origin | 含义 | 该怎么办 |
|---|---|---|
| `role-mapped` | 命中角色级绑定，**权威** | 正常 |
| `explicit-matched` | 无角色绑定，但节点显式写的 model 正好是本宿主认识的 | 正常（无角色节点的钉死逃生舱） |
| `tier-mapped` | 按档位映射到本宿主模型 | 正常 |
| `host-unmapped` | 宿主有档案，但没给这个角色/档位配模型 | `model=None`，去补 `role_models`；工作流应**优雅退回主会话内联执行**，不要崩 |
| `no-host` | 未识别宿主 / 空档案 | `model=None`，先感知宿主或补档案 |

**关键设计**：后两种返回 `None` 而不是「猜一个」。宁可明说没配，也不要静默用错模型。

---

## 4. 注册：代码只打包交接物，宿主 Agent 落盘

**注册动作由宿主 Agent 自己完成，不是仓库代码。** 原因：不同宿主注册子智能体的方式完全不同（Qoder 写 `.md` 定义文件，Antigravity 调 `define_subagent` 工具），代码无法代劳，只能**感知 → 解析 → 交接**。

### 4.1 交接物结构（register-spec）

仓库侧提供一个命令，输出这样一份 JSON：

```jsonc
{
  "host": "qoder",
  "host_source": "fingerprint",          // fingerprint | env-override | explicit | unknown
  "registration": { /* §3.2 的注册契约 */ },
  "project": "<项目目录>",
  "subagents": [
    {
      "name": "doc_reviewer",
      "description": "文档质量盲审员",
      "system_prompt": "你是一名严格的文档盲审员……",
      "enable_write_tools": false,
      "enable_mcp_tools": false,
      "_bound_tier": "pro",
      "_bound_model": "qmodel_38max",     // ← 已解析成本宿主真实 ID，宿主照抄即可
      "_model_origin": "role-mapped",
      "_host": "qoder"
    }
  ]
}
```

宿主 Agent 拿到后**不需要理解解析逻辑**，只要按 `registration` 契约把每项落成文件。这就是「代码负责正确性、宿主负责落盘」的分工。

### 4.2 Qoder 定义文件模板

```markdown
---
name: doc_reviewer
description: 文档质量盲审员
model: qmodel_38max
tools:
  - Read
  - Grep
  - Glob
---

你是一名严格的文档盲审员……
（正文 = 角色规格里 system_prompt 的原文，不要在注册时改写）
```

写到 `<项目>/.qoder/agents/doc_reviewer.md`（项目级）或 `~/.qoder/agents/doc_reviewer.md`（用户级）。

### 4.3 生效条件（容易漏）

- `model:` 只能填**内置 ID** 或 **BYOK 裸 UUID**，填 slug = 静默回落。
- **新增或改名的 agent 类型必须新开会话**才会被 Qoder 注册上。
- 改已有文件的 `model:` 值，生效时机不确定 → 见 §5 验证。
- 派发用 `Agent(subagent_type=doc_reviewer)`，**不要试图在调用处指定模型**（当前运行时没有这个参数）。

---

## 5. 验证闭环：用 `resolvedModel` 说话，不要用眼睛看配置

§1 约束 1 和 3 决定了：**静态检查配置不能作为「模型生效」的证据**。必须真实派发一次并核对运行时记录。

### 5.1 权威证据

| 要确认什么 | 去哪看 |
|---|---|
| 子代理这次派发**实际用的模型** | `~/.qoder/projects/<项目slug>/<会话id>/subagents/task-*.json` 的 **`resolvedModel`** 字段，以及结构化事件里的 `provider` / `request_id` |
| 派发时刻与参数 | `~/.qoder/logs/sessions/<项目slug>/<会话id>/segments/*.jsonl` 里的 `tool.requested`（Agent 调用） |
| 主会话模型 | 转录 `~/.qoder/projects/<proj>/<会话>.jsonl` 的 `message.model`（内部名） |
| 模型 ID 清单是否还对 | 桌面端 `main.sqlite` 的 `chat_model_preferences` + `byok_model_capability_metadata`（BYOK 以此为准，本地 `state.vscdb` 是 CLI 侧陈旧缓存） |

### 5.2 三个证据污染陷阱

1. **自动 Recap 会话**不是子代理派发（prompt 以「你正在为 Qoder 任务监控编写…Recap」开头，用 qfmodel/efficient）。
2. **后台 Bash 会话**（几百字节只有一行 config 的存根）也不是。
3. `logs/runs/*/qodercli.log` 会**回显对话文本**——助手自己写的 "kimi"、"qwen" 字样会被 grep 到，用模型名当关键词搜必被自己污染。要搜就搜结构化字段（`resolvedModel`、`tool.requested`）。

本地查不到的：**子代理逐请求的模型归属不落本地日志**，最终权威是桌面端用量面板，按派发时刻对账。

### 5.3 验证剧本（照抄可用）

1. 改完 `role_models` → 跑一次 register-spec → 让宿主 Agent 重写 `.qoder/agents/*.md`。
2. **新开一个会话**（别在原会话里验，重载时机不定）。
3. 派发一个**最小探针任务**给目标角色（比如「回复 OK」），成本几乎为零。
4. 打开对应 `task-*.json`，核对 `resolvedModel` == 你期望的内置 ID。
5. 不符 → 检查是不是填了 slug、是不是没新开会话、是不是有并行会话改了同名文件。
6. 全部角色各探针一次，把结果（`resolvedModel` + `request_id` + 时间）记进项目文档，作为基线。

---

## 6. 踩坑清单（novelFlow 真实事故）

| 坑 | 现象 | 根因 | 对策 |
|---|---|---|---|
| 节点没写 `subagent_type` | 该节点吃不到角色绑定，解析降级 | 角色绑定的键是 `subagent_type`，不是节点名 | 工作流图里**每个 agent 节点都必须写 `subagent_type`**；提供一个 `configure` 命令批量注入，并**顺手移除写死的 model 名**（保持宿主无关） |
| 按模型名猜档位 | Pro 门禁被当成 Flash 跑，质量把关失效 | `infer_tier_from_model` 看到名字里有 "flash" 就推断档位 | **删掉这个启发式**。档位只能显式声明，不能从名字推断 |
| 以为 `default_tier` 就是最终模型 | 「deai_polisher 是 flash 档，那 Qoder 下肯定用 qfmodel」——错 | qoder 的 `role_models` 把它提到了 `qmodel_38max`，角色绑定权威于档位 | 判断某角色在某宿主用什么模型，**只看 `host_profiles.<host>.role_models`** |
| 新加节点不想动注册表 | 新角色没进 7 角色表 → 掉进 `host-unmapped` | 角色表是穷举的 | 新节点写 `model_tier: pro/flash` 但**不写** `subagent_type`，走解析链第 ③ 级 `tier-mapped`，不会掉进未配置 |
| 多会话并发改同一 agent 定义 | 15:09 探针拿到正确 UUID，15:39 再探针已回落——中间另一会话 15:11 把文件改回了 slug | Qoder 定义文件是共享可变状态 | 注册文件纳入版本控制或加锁；改完立刻验证；多人/多会话协作时约定「谁负责注册文件」 |
| 批量重写工作流图打乱 diff | `configure` 用 `yaml.dump` 整体重写 graph.yaml，未提交改动的格式 diff 全乱 | 序列化工具不保留注释与排版 | 跑批量配置前先提交或 stash；或让 configure 只做最小原地修改 |
| 注册规格没给 web 工具 | 走 tier-mapped 的调研节点**无法联网**，只能靠内部知识 | 注册规格里 `enable_mcp_tools: false` | 需要联网的角色要**单独配一个带 web 工具的注册角色**，新开会话生效 |
| 静态解析当验收证据 | 「代码解析出 qmodel_38max 了，所以没问题」 | 解析正确 ≠ 派发正确（约束 1、3） | 验收必须含真实派发 + `resolvedModel` 核对 |

---

## 7. 新项目落地 Checklist

**设计阶段**

- [ ] 角色规格里**没有任何具体模型名**，只有 `default_tier`
- [ ] 工作流图里**没有任何具体模型名**，每个 agent 节点都有 `subagent_type`（或明确的 `model_tier`）
- [ ] 每个要支持的宿主都在 `host_profiles` 里有**全套** `role_models` + `tiers`，宿主之间对等，无默认
- [ ] 解析不出时返回 `None` + 明确 origin，工作流能优雅退回（内联执行/跳过），不崩不猜
- [ ] 没有「按名字猜档位」之类的启发式

**注册阶段**

- [ ] 仓库侧只提供 `register-spec` 交接物，**不代替宿主注册**
- [ ] `registration` 契约写清了：目录、文件名模式、frontmatter 字段、正文来源、是否支持按调用覆盖、是否要新开会话、**怎么验证**
- [ ] 模型 ID 全部来自已核实的清单（内置 ID 或 BYOK 裸 UUID），没有从别家宿主文档抄来的 slug

**验证阶段**

- [ ] 新开会话后，每个角色都派发过一次最小探针
- [ ] `task-*.json` 的 `resolvedModel` 与期望一致，已记录 `request_id` 与时间作为基线
- [ ] 项目文档里写清了「改模型的正确流程」：改 `role_models` → register-spec → 重写定义文件 → 新会话 → 探针核对

---

## 附录 A：Qoder 内置模型 ID（2026-09-22 实测快照）

以本机双数据源交叉核对（桌面端 `main.sqlite` + IDE 侧 `state.vscdb`，两者一致）。**ID 会随版本变化，用前请重新核对。**

| 内部 ID | 显示名 | 备注 |
|---|---|---|
| `qfmodel` | Qwen3.8-Flash | 常用 flash 档 |
| `qmodel_38max` | Qwen3.8-Max | 常用 pro 档 |
| `qmodel_latest` | Qwen3.7-Max | 选择器隐藏 |
| `qmodel` | Qwen3.7-Plus | 选择器隐藏 |
| `gfmodel` | GLM-5.3-Flash | 曾是主会话默认 |
| `gmodel` | GLM-5.3 | |
| `dmodel` / `dfmodel` | DeepSeek-V4-Pro / V4-Flash | |
| `mmodel` | MiniMax-M3 | |
| `cmodel` | Cantus | |
| `kmodel_latest` / `kmodel` | Kimi-K3 / Kimi-K2.7-Code | K3 内置当前未开放 |
| `smodel` | （显示名不在缓存） | 实测可用，曾是会话默认档之一 |
| `auto` / `ultimate` / `performance` / `efficient` | 模式别名 | |

BYOK 自定义渠道：frontmatter 用**裸 UUID**（不带 `byok:` 前缀），桌面选择键是 `byok:<UUID>`。示例 `e1584866-30e7-461c-a2aa-4c9a039a2a2b`（kimi-k3-cp）经真实子代理派发验证通过。

---

## 附录 B：novelFlow 对应实现索引

想直接读源码的话：

| 关注点 | 文件 |
|---|---|
| 宿主感知 + 解析链 + 注册交接物打包 | `shared/subagent_registry.py`（`detect_host` / `resolve_node_model` / `get_registration_definitions` / `build_registration_spec`） |
| 宿主档案与注册契约 | `subagents/manifest.json` → `host_profiles` |
| 角色规格（宿主无关，只有 tier） | `subagents/*.yaml`（7 个角色） |
| 宿主 Agent 执行指南（注册流程的散文版） | `skills/novel-runner/SKILL.md` → 「模式 4：宿主感知的子智能体注册与模型自适应挂载」 |
| Qoder 模型 ID / 日志位置原始实测 | `docs/qoder-model-routing.md` |
| 解析链测试 | `shared/test_subagent_registry.py` |
