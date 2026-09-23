# Changelog

本仓库所有版本变更都会记录在此文件。版本号遵循 [Semantic Versioning](https://semver.org/)。

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