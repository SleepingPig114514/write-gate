# write-gate

Hermes Agent 桌面端插件（装于 `%LOCALAPPDATA%\hermes\plugins\`，依赖 Hermes 的 clarify 确认卡与辅助模型体系）。确认闸门的核心职责：**动工前给你一个按钮**。不判定路径、不设时间窗；文件/记忆类写入无条件拦，命令类走状态变更黑名单（默认放行、命中才拦）——范围与计划是模型和用户之间的事。

## 运行前提：依赖 Hermes 内置的 clarify 确认卡

解锁信号完全挂在 clarify 工具的返回结果上（机械匹配读 `user_response` 字段，语义分类喂的也是它）。因此本插件只在**提供 clarify UI 的平台**（桌面端）有意义；无此 UI 的平台（oneshot/cron/qqbot/眼镜）与 clarify 被禁用的 delegation 子代理必须豁免，否则模型出卡无人可点、会话死锁——下方豁免清单即由此推出。

## 三级确认范围

| 级别 | 怎么触发 | 生效范围 | 怎么收回 |
|---|---|---|---|
| **单次回复**（默认） | 点选项「按此方案执行」 | 本轮 agent 运行内全部写入静默 | 自动：你下一条消息起重新弹卡 |
| **单次会话** | 确认卡自定义框说"别问了 / 这次都直接做" | 本会话全部静默 | 重启或新开会话（解锁态纯内存，新会话天然锁定） |
| **所有会话** | 设置 → 插件 → write-gate 拨动 | 跨会话关闭 | 拨回来 |

## 行为

拦截 `write_file` / `patch` / `memory`（无条件）、`execute_code`（代码含文件写模式，或 subprocess 参数命中状态变更黑名单）、`terminal`（命令命中状态变更黑名单，按 `&&`/`|`/`;` 切段逐段检查）。锁定时发起一律拦下，模型被迫：

1. 正文呈现方案（变更目标、目的、步骤）；
2. 调 clarify 出确认卡，选项「按此方案执行 / 取消」。

自定义框的回复由辅助 LLM 分类（走宿主 `auxiliary.approval` 任务槽模型，保守默认 NO）：同意→本轮放行；"别问了"→整会话放行；提问/拒绝/含糊→不变。点「取消」是机械短路直接判 NO，不产生任何模型调用；点「按此方案执行」机械放行。三条路径中只有自由文本意见花一次分类调用。

### terminal 黑名单（v1.1.0）

方向性契约：**默认放行，命中才拦**。漏判 = 退回无闸门（不恶化）；误判 = 多弹一张卡。覆盖十类状态变更：服务/系统状态（net start / sc config / nssm set 等，查询类 `sc query`、`netstat` 放行）、计划任务创建删除、杀进程（taskkill / Stop-Process）、注册表写入、文件系统变更（rm / mv / cp / Remove-Item）、包安装（winget / npm / pip install）、git 写操作（push / commit / reset，status / log 放行）、PowerShell 变更动词（Set-Service / Restart-Computer，Set-Location 放行）、wmic 变更子命令、hermes 自身变更（update / gateway install，serve / --version 放行）。名单以带注释常量 `_STATE_PATTERNS` 维护：只在真实漏判后补条目，每条写明拦什么/放什么。

## 豁免（不问直接过）

- 非桌面会话：oneshot / cron / qqbot / 眼镜（无确认卡 UI）；
- delegation 子代理（clarify 被禁用，防死锁）；
- 纯读工具（read_file/search_files 等）本就不在拦截面；
- 环境变量 `WRITE_GATE=off`。

## 已知边界（如实）

- 放行范围内"任意写入"静默——被骗授权的最坏情况≈退回无插件状态，不会更差（插件保证的只是"没按过按钮不许动工"）；
- 自定义框的语义分类存在误判可能（保守偏向"不放行"，代价是最多多弹一张卡）；点选项是机械匹配，零误判；
- execute_code 正则防"糊涂"不防"执意"——刻意混淆代码可绕过；防线是 checkpoints + 事后回查；
- terminal 黑名单同样防"糊涂"不防"执意"：`powershell -EncodedCommand <base64>` 与 `cmd /c "<嵌套命令>"` 的载荷内容对正则不可见，只能拦外层动词命中；刻意把变更藏进编码载荷可绕过（v1.1.0 已知盲区，验收样本里如实标注）；重定向写文件（`echo x > file`）暂不入名单——漏判后果仅是文件写，而文件写通道本身已被 write_file/patch 管辖；
- 插件内部任何异常 = 放行（fail-open），不会卡死会话；日志见 Hermes 日志 `write-gate` 前缀。

## 安装

把本目录（`write-gate/`）整体放入 `%LOCALAPPDATA%\hermes\plugins\`，在 Hermes 设置 → 插件中启用 `write-gate`（或 config.yaml `plugins.enabled` 加入），重启生效。

## License

[MIT](LICENSE)

