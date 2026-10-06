# Changelog

本仓库所有版本变更都会记录在此文件。版本号遵循 [Semantic Versioning](https://semver.org/)。

## [1.1.1] - 2026-10-07

### 变更

- 确认回复判定收窄为三条固定路径：点「按此方案执行」→ 机械放行（原有）；点「取消」→ 机械判 NO 短路，**不再调用 LLM**（此前用户明确拒绝也要白烧一次分类）；仅自定义框自由文本走语义分类
- 语义分类路由改走宿主 `auxiliary.approval` 任务槽（`task="approval"`），与主模型解耦：不再占用主会话模型推理尾延迟；需宿主配置 `plugins.entries.write-gate.llm.allow_task_override: true`（插件 LLM 路由默认 fail-closed），旗标缺失时分类抛信任拒绝→按 NO 保守处理，锁定安全不受影响
- `_BLOCK_MSG` 出卡契约收紧：执行确认卡选项恒为「按此方案执行/取消」两项 + 自定义框，同意范围以问题正文为准；方案圈定类多选卡不受约束（两段式：方案归对话，执行归死确认）
- README 同步；`_CLASSIFY_INSTRUCTIONS` 判定口径不变

## [1.1.0] - 2026-10-07

### 概述

扩面：命令/系统状态变更纳入闸门管辖。起因是一次真实越权——Hermes 自更新把服务化的 `hermes.exe` 入口换成了 `hermes.cmd`，修复过程中 agent 经 `execute_code → subprocess → powershell → nssm set` 改了服务配置，全程未触任何确认：文件写拦得住，命令拦不住（terminal 不在受管面，execute_code 写正则只认文件写模式）。

### 变更

- `_MANAGED` 增加 `terminal`：命令按 `&&`/`|`/`;`/换行切段，任一段命中 `_STATE_PATTERNS` 黑名单即拦；默认放行（黑名单方向，误判代价 = 多弹一卡）
- `_STATE_PATTERNS`（terminal 与 execute_code 共用，带注释常量，扩充原则见 README）：服务状态（net/sc 变更子命令、nssm 变更动词）、计划任务、杀进程、注册表写、文件系统变更（rm/mv/cp/Remove-Item 等）、包安装、git 写操作、PowerShell 变更动词（限系统对象）、wmic 变更、hermes 自身变更子命令
- `execute_code` 判定升级：除原文件写模式外，新增括号配平抽取 `subprocess.*` 调用参数（原始 blob + 字符串字面量还原两个视角）比对黑名单——封"在代码里 shell 出去改状态"这条绕行路线
- 修复 v1.0.0 遗留笔误：`_WRITE_PATTERNS` 重定向检测字符类误写成 `[>'>]`（混入撇号），导致所有带引号参数的 subprocess 调用被误判为写；修正为 `>{1,2}`，只读 subprocess 调用恢复放行
- 阻断文案同步：拦的是"写操作/命令"，方案呈现要求含命令级目标

### 已知盲区（本版不解决，如实）

- `powershell -EncodedCommand <base64>` / `cmd /c "<嵌套>"` 载荷内容不可见，只拦外层动词命中
- 重定向写文件（`> file`）不入 terminal 名单（漏判后果 = 文件写，已被 write_file/patch 通道管辖）
- 引号内含 `&&` 的命令会被切段（罕见，代价仅多弹一卡）

### 验收

离线断言集（scripts/test_gate.py）：7 类黑名单必拦 + 11 类只读必放 + 2 类 subprocess 注入必拦 + 引号 blob + 解锁回归；EncodedCommand 盲区样本单独列出、不作通过断言。

## [1.0.0] - 2026-09-27

### 概述

write-gate 是一个确认闸门插件：任何 `write_file` / `patch` / `memory` / `execute_code`（代码含写模式）的调用，在桌面会话锁定状态下都会被拦截，模型必须先呈现方案并调 `clarify` 出确认卡，用户批准后才能落地。

### 行为

- 拦截面：`write_file` / `patch` / `memory` / `execute_code`（含 `open('w'…)` / `shutil.copy|remove|…` / `os.remove|unlink|…` / `.write_text|.write_bytes|.touch|.mkdir|.unlink|.rename` / `subprocess.*…>` 写模式正则）
- 锁定判定：`session.source == "desktop"` 且 `parent_session_id` 为空时才生效；非 desktop 来源（oneshot / cron / qqbot / 眼镜）、delegation 子代理、环境变量 `WRITE_GATE=off` 自动豁免
- 解锁记录：进程内 `_unlock` 字典 `(scope, turn_id)`，scope ∈ {`turn`, `session`}
- 插件异常 = fail-open（放行，不卡死会话）

### 三级确认范围

- **单次回复**（默认）：点选项「按此方案执行」→ 本轮 agent 运行内全部写入静默；用户下一条消息起自动重新锁定
- **单次会话**：确认卡自定义框说"别问了 / 这次都直接做" → 本会话全部静默；反悔方式 = 重启或新开会话（解锁态纯内存）
- **所有会话**：Hermes 设置 → 插件 → write-gate 拨动

### 已知边界（如实）

- 放行范围内"任意写入"静默——被骗授权的最坏情况≈退回无插件状态
- 自定义框语义分类由主模型判定，保守默认 NO（拒绝），不通过则维持锁定
- `execute_code` 正则防"糊涂"不防"执意"
- `terminal` 命令不经本插件，由 Hermes 原生 `approvals.mode` 覆盖
- 插件内部任何异常 = 放行（fail-open）

### 依赖

- Hermes 内置 `clarify` 确认卡 + 辅助 LLM 体系
- Python 3.11+（用到 `sqlite3` + `typing`）

### 安装

把本目录整体放入 `%LOCALAPPDATA%\hermes\plugins\`，在 Hermes 设置 → 插件中启用 `write-gate`（或在 `config.yaml` 的 `plugins.enabled` 加入），重启生效。

[MIT](LICENSE)