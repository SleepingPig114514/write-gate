# write-gate

Hermes Agent 桌面端插件（装于 `%LOCALAPPDATA%\hermes\plugins\`，依赖 Hermes 的 clarify 确认卡与辅助模型体系）。确认闸门的核心职责：**动工前给你一个按钮**。不判定路径、不设时间窗、不维护白名单——范围与计划是模型和用户之间的事。

## 运行前提：依赖 Hermes 内置的 clarify 确认卡

解锁信号完全挂在 clarify 工具的返回结果上（机械匹配读 `user_response` 字段，语义分类喂的也是它）。因此本插件只在**提供 clarify UI 的平台**（桌面端）有意义；无此 UI 的平台（oneshot/cron/qqbot/眼镜）与 clarify 被禁用的 delegation 子代理必须豁免，否则模型出卡无人可点、会话死锁——下方豁免清单即由此推出。

## 三级确认范围

| 级别 | 怎么触发 | 生效范围 | 怎么收回 |
|---|---|---|---|
| **单次回复**（默认） | 点选项「按此方案执行」 | 本轮 agent 运行内全部写入静默 | 自动：你下一条消息起重新弹卡 |
| **单次会话** | 确认卡自定义框说"别问了 / 这次都直接做" | 本会话全部静默 | 重启或新开会话（解锁态纯内存，新会话天然锁定） |
| **所有会话** | 设置 → 插件 → write-gate 拨动 | 跨会话关闭 | 拨回来 |

## 行为

拦截 `write_file` / `patch` / `memory` / `execute_code`（代码含写模式：open('w')、shutil.copy、os.remove 等正则）。锁定时发起一律拦下，模型被迫：

1. 正文呈现方案（写入目标、目的、步骤）；
2. 调 clarify 出确认卡，选项「按此方案执行 / 取消」。

自定义框的回复由辅助 LLM 分类（走主模型，保守默认 NO）：同意→本轮放行；"别问了"→整会话放行；提问/拒绝/含糊→不变。

## 豁免（不问直接过）

- 非桌面会话：oneshot / cron / qqbot / 眼镜（无确认卡 UI）；
- delegation 子代理（clarify 被禁用，防死锁）；
- 纯读工具（read_file/search_files 等）本就不在拦截面；
- 环境变量 `WRITE_GATE=off`。

## 已知边界（如实）

- 放行范围内"任意写入"静默——被骗授权的最坏情况≈退回无插件状态，不会更差（插件保证的只是"没按过按钮不许动工"）；
- 自定义框的语义分类存在误判可能（保守偏向"不放行"，代价是最多多弹一张卡）；点选项是机械匹配，零误判；
- execute_code 正则防"糊涂"不防"执意"——刻意混淆代码可绕过；防线是 checkpoints + 事后回查；
- terminal 命令不经本插件，由 Hermes 原生 `approvals.mode` 覆盖（本仓库不做保证，随宿主配置）；
- 插件内部任何异常 = 放行（fail-open），不会卡死会话；日志见 Hermes 日志 `write-gate` 前缀。

## 安装

把本目录（`write-gate/`）整体放入 `%LOCALAPPDATA%\hermes\plugins\`，在 Hermes 设置 → 插件中启用 `write-gate`（或 config.yaml `plugins.enabled` 加入），重启生效。

## License

[MIT](LICENSE)

