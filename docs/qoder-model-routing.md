# Qoder 模型配置与子代理路由机制

> 2026-09-21 在 videoProduction 项目实测总结。适用于所有用 Qoder 的项目（含本项目 novelFlow）。

## 1. Qoder 的模型从哪来（三层）

**系统内置模型**（source=system，走 Qoder 会员/订阅额度）。内部名以 `%APPDATA%/Qoder/User/globalStorage/state.vscdb` 的 `aicoding.modelConfigs.cache` 为准（2026-09-21 快照）：

| 内部名 | 显示名 | 备注 |
|---|---|---|
| `gfmodel` | GLM-5.3-Flash | 主会话默认 |
| `qfmodel` | Qwen3.8-Flash | 启用中 |
| `qmodel_38max` | Qwen3.8-Max | 启用中 |
| `kmodel_latest` | Kimi-K3 | 默认停用，要用先在模型选择器启用 |
| `kmodel` | Kimi-K2.7-Code | 停用 |
| `cmodel` / `efficient` / `ultimate` / `mmodel` 等 | Cantus / Efficient / Ultimate / MiniMax-M3 | 备用档位 |

**自定义 BYOK 渠道**（配置在账号服务端，走自己订阅的 API 额度）。模型选择器「自定义」页签可见：provider `bailian`（Token Plan：Qwen-3.8-Flash / Qwen-3.8-Max 等）、provider `kimi`（Kimi-K3 / Kimi-for-coding，来自 Kimi 订阅 API）。**本地 state.vscdb 是 CLI 侧的陈旧缓存，查 BYOK 以桌面端模型管理/服务端为准**。

**独立插件**：如 moonshot-ai.kimi-code（Kimi Code 侧边栏），用自己的订阅登录，但 Qoder 的 agent 派发用不到它里面的模型。

## 2. 模型名的三种形态（写错就静默回落）

| 形态 | 例子 | 用在哪 |
|---|---|---|
| 内部名 | `qfmodel`、`qmodel_38max`、`kmodel_latest` | 子代理会话 config 实际记录的形式；**frontmatter 引用系统模型写这个** |
| 显示名 | `Qwen3.8-Flash`、`Kimi-K3` | 模型选择器、hook 回显；会变拼写（Qwen-3.8-Flash→Qwen3.8-Flash），别依赖 |
| 上游 slug | `kimi-k3`、`kimi-for-coding`、`qwen3.8-max-tp` | BYOK 渠道的 API 模型名；⚠ **不能写进 frontmatter**（见下方更正） |

frontmatter 的值写错**不会报错**，会静默回落到会话默认模型（`gfmodel`）——最危险的坑，只能靠用量面板事后发现。

> **⚠ 2026-09-22 更正（真实派发 A/B 实测，取代上表原结论）**：frontmatter 引用 BYOK 渠道模型必须写**裸 UUID**（不带 `byok:` 前缀，如 `e1584866-30e7-461c-a2aa-4c9a039a2a2b`），写上游 slug（`kimi-k3`）会**静默回落**到会话当前模型。同一 agent 定义文件两次探针：填裸 UUID → `resolvedModel=e1584866…`、`provider=kimi`；被改回 `kimi-k3` → `resolvedModel=qmodel_38max`、`provider=qoder`。即 frontmatter 只认**内置系统 ID** 与 **BYOK 裸 UUID** 两种形态。

## 3. agent / subagent 的路由机制

- 定义文件两处：**用户级** `C:\Users\Administrator\.qoder\agents\*.md`（全项目共享）、**项目级** `<项目>\.qoder\agents\*.md`（仅本项目）。frontmatter 含 `name` / `description` / `model` / `tools`。
- **路由规则**：Agent 工具派发时不带 model 参数 → frontmatter `model:` 说了算；派发时显式带 model 参数 → 单次覆盖定义。
  > **⚠ 2026-09-24 更正**：当前 Qoder CLI 运行时的 `Agent` 派发工具**不暴露 `model` 参数**（仅有 `subagent_type`/`prompt`/`description`/`run_in_background` 等），因此**无法按调用覆盖**，模型在注册时由定义文件钉死。上面「单次覆盖」一条是 2026-09-21 在 videoProduction 的记录，与当前运行时矛盾（疑为版本差异或未真正透传）。**设计一律按「钉死」处理**，与 `subagents/manifest.json` 的 `per_call_model_override: false` 一致。详见 [qoder-subagent-model-config-guide.md](./qoder-subagent-model-config-guide.md) §1。
- **边界**：面板 runPrompt 按钮 → 主会话直接干活，用的是主会话当时的模型，与 frontmatter 无关。frontmatter 只在"真派发子代理"时生效。
- **生效时机**：改完定义文件要重载/重启会话才生效（启动时加载）。
- videoProduction 的定稿路由（参考）：deai-reviewer→`kimi-k3`（自定义渠道，省会员额度）；researcher/implementer-flash→`qfmodel`；script-writer/evidence-injector/storyboard/spec-reviewer-max/code-quality-reviewer-max→`qmodel_38max`。

## 4. novelFlow 的接法（已落地：纯宿主驱动）

模型的唯一来源是"感知到的宿主"。`subagents/*.yaml` 与预设里**不再写任何具体模型名**，只有 `default_tier`（flash/pro）这个跨宿主抽象；具体模型只存在于 `subagents/manifest.json` 的 `host_profiles.<host>` 里，各宿主对等：

- `host_profiles.qoder.role_models`：7 个角色 → Qoder 内置 ID（flash 档 `qfmodel`、pro 档 `qmodel_38max`）。**Qoder 只认内置系统 ID 与 BYOK 裸 UUID**，`gemini-*`/`claude-*`/`kimi-k3` 等上游 slug 会静默回落到会话当前模型，所以这里绝不能填 slug。
- `host_profiles.antigravity.role_models`：同样 7 个角色 → gemini/claude 名，与 qoder 完全对等，不再是"出厂默认"。

运行时解析链（`shared/subagent_registry.py: resolve_node_model`）：感知宿主 →（角色 `role_models` 权威）→（无角色时显式 model 且宿主认识）→ 档位 `tiers` 映射 → 都没命中则报 `host-unmapped`（model=None），**任何情况下都不回落到别家宿主的模型名**。

接 Qoder 原生子代理：宿主 Agent 读取 `python shared/subagent_registry.py register-spec --host qoder` 的交接物，按 `registration` 契约在 `<项目>\.qoder\agents\<name>.md` 写定义文件，`model:` 填交接物里的 `_bound_model`（已解析成内置 ID），正文用 yaml 的 `system_prompt`。注册动作由宿主 Agent 完成，不是仓库代码；新增/改名的 agent 类型须新开会话才注册得上。

## 5. 怎么验证"模型真的被用了"

本地能查的：
- 派发时刻与参数：`~/.qoder/logs/sessions/<项目slug>/<会话id>/segments/*.jsonl` 里的 `tool.requested`（Agent 调用）
- 主会话模型：转录 `~/.qoder/projects/<proj>/<会话>.jsonl` 的 `message.model` 字段（内部名）
- 注册表：grep state.vscdb（注意是陈旧缓存）

本地查不到的：**子代理逐请求的模型归属不落本地日志**，权威只在桌面端用量面板——按派发时刻对账。

三个证据污染陷阱：
1. 自动 Recap 会话（prompt 以「你正在为 Qoder 任务监控编写…Recap」开头，用 qfmodel/efficient）不是子代理派发；
2. 后台 Bash 会话（287 字节只有一行 config 的存根）也不是；
3. `logs/runs/*/qodercli.log` 会回显对话文本（包括助手自己写的"kimi""qwen"字样），grep 模型名必被自己污染。
