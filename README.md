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

## 确认后自动转派子代理（v1.1.5，默认关）

桌面端「能力 → 插件 → write-gate」页的开关（`plugin.yaml` 的 `config_schema` → `plugins.entries.write-gate.settings.delegate_after_approval`，`ctx.get_config` 每次现读，拨动即生效、不用重启网关）。

| 开关 | 点「按此方案执行」之后发生什么 |
|---|---|
| **关**（默认） | 与 v1.1.4 完全一致：主模型重试那次写入即放行 |
| **开** | 第一个已批准的写调用不放行，改为拦下并把 `_DELEGATE_MSG` 交给模型：要求用 `delegate_task` 派子代理执行，brief 写明允许改的绝对路径清单、禁止触碰范围、回报「改了哪些文件 + 每个文件字节数与 SHA256」 |

- 只管「按此方案执行」产生的单轮放行；单次会话级（"别问了"）不转派——那种放行本该免问，否则每条消息都白派一个子代理。
- `memory` 不转派：子代理没有 memory 工具，转过去必然空转。
- 同一轮再重试**仍然拦**并重复同一份转派指令（`_redirected[session_id]`，方案 B：重试不能把转派绕过去）；`turn_id` 变化或消息结束时清空，下一轮 `_unlock` 失效 = 回到“未确认”、需重新批准，所以不放行也不会死锁。
- 开关读不到 / 读失败一律按关闭处理。
- **阈值 `delegate_min_lines`**（v1.1.6，默认 `0` = 不设阈值 = 全部转派）：**本轮累计**改动行数不超过它就直写、不派子代理（等于阈值也直写）；同一轮多次写入会累加，累计越线后转派当次调用（已落盘的前几次不回收），`turn_id` 变化或消息结束时清零。`patch` 按 `new_string` 行数算（纯删除按 `old_string` 行数）；`write_file` 在目标存在且 ≤ 2 MB 时用 `difflib` 比真实改动量（改 1 行 = 1），相对路径先按会话 `cwd` 解析，读不到则按 `content` 全文行数算；`execute_code` / `terminal` 估不出，始终转派且不参与累加。
- 派发前先用 `delegate_task(action='list')` 看有没有在跑的子代理：**这次的改动文件与它手上的重合，就用 `action='steer'` 把要求追加给它**（同一个写者不会互相覆盖），不新派；文件不重合的独立新活才新派；判不出就 steer。子代理之间不互相等待——不要写 sleep 或轮询另一个子代理的产出（轮询判据不可能精准，实测 450 秒任务里 434 秒是空等）。steer 之后要确认它的回执覆盖了追加内容，没覆盖就等它结束再补派。
- 插件本身不派子代理、不代写 brief，它只换一句返回给模型的话；子代理会话照旧豁免——这是**刻意**使用「把写入外包给子代理」这条既有通道，不是新开的口子。

## 行为

拦截 `write_file` / `patch` / `memory`（无条件）、`execute_code`（代码含文件写模式——含 `open(f,'r+')` 这类"读改"模式、调用 `hermes_tools` 程序化写助手 write_file/patch/terminal，或 subprocess 参数命中状态变更黑名单）、`terminal`（命令命中状态变更黑名单，按 `&&`/`|`/`;` 切段逐段检查，匹配不区分大小写）。锁定时发起一律拦下，模型被迫：

1. 正文呈现方案（变更目标、目的、步骤）；
2. 调 clarify 出确认卡，选项「按此方案执行 / 取消」。

自定义框的回复由辅助 LLM 分类（走宿主 `auxiliary.approval` 任务槽模型，保守默认 NO）：同意→本轮放行；"别问了"→整会话放行；提问/拒绝/含糊→不变。点「取消」是机械短路直接判 NO，不产生任何模型调用；点「按此方案执行」机械放行。三条路径中只有自由文本意见花一次分类调用。**判定只认选项含「按此方案执行」的闸门确认卡**——普通业务提问的回答（选项是业务选项）不会开闸，也不产生分类调用。

### terminal 黑名单（v1.1.3）

方向性契约：**默认放行，命中才拦**。漏判 = 退回无闸门（不恶化）；误判 = 多弹一张卡。覆盖十一类状态变更，匹配一律不区分大小写（Windows 命令不区分大小写，`DEL` / `RM` / `GIT PUSH` 与 `rm` / `git push` 同等对待）：服务/系统状态（net start / sc config / nssm set 等，查询类 `sc query`、`netstat` 放行）、计划任务创建删除、杀进程（taskkill / Stop-Process）、注册表写入、文件系统变更（rm / del / mv / cp / Remove-Item）、包安装（winget / npm / pip install）、git 写操作（push / commit / reset，status / log 放行）、PowerShell 变更动词（Set-Service / Restart-Computer / **Set-Content / Out-File / Add-Content / Tee-Object / Set-ItemProperty / Export-Csv**，Set-Location 与 Get-* 读取、`New-Object` 内存构造放行）、wmic 变更子命令、hermes 自身变更（update / gateway install，serve / --version 放行）。名单以带注释常量 `_STATE_PATTERNS` 维护：只在真实漏判后补条目，每条写明拦什么/放什么，并标注**可否被探参数降级**。

**探查降级（v1.1.3 收紧）**：段尾挂 `--help` / `-h` / `--dry-run` / `/?` 且其后不再跟真实操作数时，只对标记"可降级"的类目免检——包安装、包管理（pip/npm/uv…）、hermes 自身、git 写操作这四类（这些 CLI 遇 `--help` 会先打印帮助退出，且操作可重复、可回滚）。删除、杀进程、服务停止、注册表写、文件系统变更、wmic、PowerShell 变更动词**永不降级**：`rm -rf <path> --help` 照拦（v1.1.0–v1.1.2 是整段免检，等于危险命令尾挂一个 `--help` 就能绕过闸门）。

## 豁免（不问直接过）

- 非桌面会话：oneshot / cron / qqbot / 眼镜（无确认卡 UI）；
- delegation 子代理（clarify 被禁用，防死锁）；
- 纯读工具（read_file/search_files 等）本就不在拦截面；
- 环境变量 `WRITE_GATE=off`。

## 已知边界（如实）

- 放行范围内"任意写入"静默——被骗授权的最坏情况≈退回无插件状态，不会更差（插件保证的只是"没按过按钮不许动工"）；
- 自定义框的语义分类存在误判可能（保守偏向"不放行"，代价是最多多弹一张卡）；点选项是机械匹配，零误判；
- execute_code 正则防"糊涂"不防"执意"——刻意混淆代码可绕过；`from hermes_tools import write_file/patch/terminal` 已纳管（v1.1.2），但 `import hermes_tools as ht` 别名形态仍是盲区；防线是 checkpoints + 事后回查；
- terminal 黑名单同样防"糊涂"不防"执意"：`powershell -EncodedCommand <base64>` 与 `cmd /c "<嵌套命令>"` 的载荷内容对正则不可见，只能拦外层动词命中；刻意把变更藏进编码载荷可绕过（v1.1.0 已知盲区，验收样本里如实标注）；重定向写文件（`echo x > file`）暂不入名单——漏判后果仅是文件写，而文件写通道本身已被 write_file/patch 管辖；
- 与上条同一边界的还有**内联解释器写盘**：`python -c "open(...,'w')"`、`node -e`、`sed -i`、`dd of=` 都不命中黑名单（Windows 上的 Git Bash 里都是日常写法，属于习惯而非刻意混淆）；
- **闸门只覆盖 5 个通道**（write_file / patch / memory / execute_code / terminal）：`skill_manage`、`cronjob_manage`、`process_manage`、`computer_use`、`browser_exec`、`manage_catalog` 等不在拦截面；delegation 子会话因 clarify 被禁用而整类豁免（防死锁）⇒ 把写入"外包"给子代理可以绕过闸门——与 EncodedCommand 同属"防执意"边界（v1.1.5 起可用上面的开关把这条通道**主动**用于已批准的写入，那是用户自己选的路，不算绕过）；
- **只读脚本也可能被误拦**：execute_code 的判定走源码文本正则，代码里出现 `os.remove` / `shutil.copy` 这类字面量（哪怕只是用例标签或文档字符串）即命中写模式。根治要改成 AST 判定（读 Call 节点的函数名与 mode 实参），未做；
- 探参数降级仍可被利用：可降级的那四类里"变更命令 + `--help`"能骗过降级（这些 CLI 的 `--help` 会先退栈，属可接受代价）；
- 插件内部任何异常 = 放行（fail-open），不会卡死会话；日志见 Hermes 日志 `write-gate` 前缀。

## 安装

把本目录（`write-gate/`）整体放入 `%LOCALAPPDATA%\hermes\plugins\`，在 Hermes 设置 → 插件中启用 `write-gate`（或 config.yaml `plugins.enabled` 加入），重启生效。

## License

[MIT](LICENSE)

