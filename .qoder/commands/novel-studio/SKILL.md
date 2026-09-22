---
name: novel-studio
description: Use when 用户调用 /novel-studio 打开或继续当前小说的可编辑工作台，并希望在主对话确认后再执行。
---

以本文件所在目录向上三级作为 novelFlow 仓库根目录，读取该仓库的 `skills/novel-studio/SKILL.md`，完整遵循其中的准备、启动、真实渲染回执和主对话确认流程。

将用户参数交给该入口解析。不要在此复制引擎实现、小说历史或专家提示词。收到页面 ready 后必须在主对话询问并等待用户，不执行正文节点；无法找到正典 skill 时报告缺失，不猜测启动命令。
