# Changelog

本仓库所有版本变更都会记录在此文件。版本号遵循 [Semantic Versioning](https://semver.org/)。

## [1.1.7] - 2026-11-22

### 修改

- **`_DELEGATE_MSG` 第 5 条改写（并发占用）**：把「等它写完之后再读或改」改成「指定一个可判定的写完信号（末行标记 / 旁边的 `.done` 文件 / 大小连续两次检查不变），确认信号后再**采用**读到的内容」。起因：2026-11-22 三子代理实测发现两点——①判断是否写完本身就要读文件，轮询必然读到中间态（实测读到 5 行 `STAGE1`、10 行 `STAGE2` 各两次）；②不指定完成信号时子代理无从判定"写完了"，等待条款等于空话。
- **`_DELEGATE_MSG` 第 2 条补半句**：禁止触碰范围里加「临时文件只写 TMPDIR 并收尾删除」。起因：实测子代理会就地建临时文件核对哈希（虽会自己删），污染工作区，并让「只改了一个文件」的回报失真。
- **阈值改为按轮累计**：`delegate_min_lines` 从「单次改动量」改为「本轮累计改动行数」——同轮多次写入会累加，累计越线后转派当次调用（已落盘的前几次不回收），`turn_id` 变化或消息结束时清零。起因：用户指出零碎改多个文件时按次判定拦不住（每次 15 行、改 5 个文件全部直写）。

## [1.1.6] - 2026-11-22

### 新增

- **改动行数阈值 `delegate_min_lines`**（桌面端「能力 → 插件 → write-gate」，默认 `0` = 不设阈值 = 全部转派，即 1.1.5 行为）：改动行数低于阈值时直接写入、不派子代理。行数估算：`patch` 取 `new_string` 行数；`write_file` 在目标存在且 ≤ 2 MB 时用 `difflib.SequenceMatcher` 比真实改动量（改 1 行 = 1，不是 2），相对路径先按会话 `cwd` 解析，读不到则退回 `content` 全文行数；`execute_code` / `terminal` 估不出，始终转派。`patch` 缺失 `new_string`（V4A 多文件形态）也按估不出处理。
- **`_DELEGATE_MSG` 第 5 条**：派发前用 `delegate_task(action='list')` 核对仍在跑的子代理——同一文件双方都只读可直接并行，任一方要写则在 brief 里写明该文件正由谁使用、要求子代理等它写完之后再读或改，等不到就先做其余部分。

### 验收

`scripts/test_gate.py` 由 96 条扩到 111 条，失败 0（新增：阈值 0 / 1 行 / 12 行 / 新文件 / 绝对路径覆盖 / 相对路径解析 / terminal 估不出 / execute_code 估不出 / patch 缺 new_string / memory / SESSION 级 / 兜底放行 / 第 5 条在位 / 前四条未改动）。

## [1.1.5] - 2026-11-22

### 新增（默认关闭，关闭态行为与 1.1.4 逐字节一致）

- **确认后自动转派子代理**：开关在桌面端「能力 → 插件 → write-gate」（`plugin.yaml` 的 `config_schema` → `plugins.entries.write-gate.settings.delegate_after_approval`，`ctx.get_config` 每次现读，拨动即生效、免重启）。打开后点「按此方案执行」不再让主模型重试那次写入，而是拦下并返回 `_DELEGATE_MSG`，要求用 `delegate_task` 派子代理执行，brief 必须写清允许改的绝对路径清单、禁止触碰范围、以及「改了哪些文件 + 每个文件字节数与 SHA256」的回报要求。
  - 只对「按此方案执行」产生的单轮放行生效；`SESSION` 级（"别问了"）保持旧行为，否则那种会话会每条消息派一个子代理。
  - `memory` 不转派：子代理没有 memory 工具（工具层禁用），转过去必然空转。
  - 兜底不死锁：`_redirected[session_id]` 记本轮已转派，同一轮再重试直接放行；`turn_id` 变化或 `on_session_end` 时清空。
  - 开关读不到/读失败一律按关闭处理 ⇒ 退回旧行为。

### 补记（1.1.4，此前只存在于运行时副本，仓库无此提交）

- **来源白名单改为正面判据**：`_exempt` 由「来源 != desktop 就豁免」改为「来源不在 `_INTERACTIVE_SOURCES`（desktop/local/gui/tui）才豁免」。2026-10-27 起桌面端会话来源记为 `local`（本机 `state.db` 实测存在 `gui`/`local` 两类），旧负向判据会让全部桌面会话被静默豁免、闸门一次都不拦。

## [1.1.3] - 2026-10-16

### 概述

外部代码锐评（六条指控）复核后确认的**机械级漏判**修复。逐条在源码取证：4 条实锤、1 条属范围选择、1 条部分成立；另外自查出 3 条锐评没看到的同源问题（第 5 类缺 `re.I`、`_MANAGED` 覆盖只有 5 个通道、只读分析脚本会被字符串字面量误拦）。本节只改机械一致性，不扩大拦截面。

### 修复

- **大小写不一致**：`_STATE_PATTERNS` 17 条里第 5 类（`rm|rmdir|del|erase|ren|unlink`）与第 7 类（`git`）漏 `re.I`，而 Windows 命令不区分大小写 ⇒ `GIT PUSH`、`DEL /f x`、cmd 的 `REN`、PowerShell 别名 `RM` 全部放行。两类补齐 `re.I`。
- **探查降级成了危险命令的免检通行证**：`_segment_is_probe` 命中 `--help/-h/--dry-run/?` 即整段跳过黑名单，`rm -rf <path> --help`（以及 `taskkill … /?`、`reg add … --help`、`net stop … -h`）一行绕过闸门。现改为**按条目标记可降级**：`_STATE_PATTERNS` 由「模式列表」改为「(正则, 可否降级)」，仅包安装/包管理/hermes 自身/git 写操作四类可降级，删除、杀进程、服务停止、注册表写、文件系统变更、wmic、PowerShell 变更动词一律不可降级。原有的"`hermes gateway install --help` 不该误伤"收益保留。
- **`open` 写模式漏 `r+`**：字符类 `[wax][+btu]*` 不含 r 开头，`open(f,'r+')` / `'r+b'` / `'rb+'` 这类"读改"模式静默落盘。改为 `(?:[rbtu]*[wax][+btu]*|[rbtu]*\+[btu]*)`，纯只读 `r` / `rb` / `rt` 仍放行。
- **PowerShell 写文件 cmdlet 缺席**：旧名词表里没有 `Content` / `Csv` / `ItemProperty`，动词表里没有 `Export` / `Out` / `Tee` ⇒ `Set-Content` / `Add-Content` / `Out-File` / `Tee-Object` / `Set-ItemProperty` / `Export-Csv` 一条都不拦（作者原以"文件写归 write_file/patch 管"为理由，但闸门管不住模型选哪条通道，且这些是 PowerShell 用户的默认写法，属"糊涂"不属"执意"）。现补齐，并刻意**不含 `Object` 名词**以免误伤 `New-Object` 这类纯内存构造。
- **机械放行 `startswith` 偏宽**：用户回复此前用 `startswith(「按此方案执行」)` 判定，在确认卡里"引用"选项发问（如"按此方案执行是什么意思？"）会被机械放行整轮。收紧为"与标记精确一致，或与卡上某个以标记开头的选项精确一致（点选项＝选项原文回填）"；卡身份识别仍用 `startswith`（闸门卡选项常带括号后缀，用精确匹配会静默丢卡）。

### 已知边界补充（README 同步）

- 内联解释器写盘不拦：`python -c "open(...,'w')"`、`node -e`、`sed -i`、`dd of=`；
- 闸门只覆盖 5 个通道 + 子会话整类豁免 ⇒ 外包给子代理可绕过（与 EncodedCommand 同一边界）；
- 只读分析脚本可能被字符串字面量误拦（判定走源码文本正则，非 AST）；
- 可降级类目仍可被"变更命令 + `--help`"骗过（CLI 遇 `--help` 先退栈，属可接受代价）。

### 残余盲区（如实，不解决）

- `import hermes_tools as ht` 别名导入（v1.1.2 起列为盲区，本版未动）；
- `powershell -EncodedCommand` / `cmd /c "<嵌套>"` 载荷不可见（v1.1.0 起）；
- 跨平台命令（`systemctl` / `apt` / `brew` / `launchctl`）不在名单——目标平台是 Windows，属范围选择而非言行不一（`wsl rm -rf …` 仍会被第 5 类命中）。

### 验收

`scripts/test_gate.py` 由 78 条扩到 **96 条断言，失败 0**（新增：大小写 4 条、尾挂 `--help`/`/?` 反例 4 条、PowerShell 写文件 5 条、`open r+` 系 3 条、只读模式护栏 2 条、探参数正例 4 条、机械放行收紧 2 条）。`EncodedCommand` 盲区样本仍单独打印、不作通过断言。

## [1.1.2] - 2026-10-10

### 修复（两处真实漏判，均由用户实机会话实测暴露）

- **clarify 判定范围外延**：`_on_post_tool_call` 此前对**任何** `clarify` 的回答做同意判定，不看这张卡是不是闸门自己发的确认卡。后果：用户对一次普通业务提问答"好 / 可以 / 做"，会被语义分类判成 TURN，把整轮写入错误放行（2026-10-10 14:28 实测：一次"要不要做测试"的提问答"做，测一下…"，整轮解锁）。现加选项过滤——仅当卡上 `choices_offered` 含「按此方案执行」才处理；业务提问的回答零分类、零影响。
- **`execute_code` 经 `hermes_tools` 绕过闸门**：`from hermes_tools import write_file / patch / terminal` 在 execute_code 内直接落盘，不经过工具层 `pre_tool_call` 钩子；旧 `_WRITE_PATTERNS` 只认 `open(…,'w')` / `shutil` / `os.` / `.write_text` 等形态，一条都不命中，该通道完全漏管（2026-10-10 实测：锁定态下 execute_code 内 write_file 写盘成功，而同一轮直接 write_file 被拦）。现补两条静态模式捕获直接调用形态。

### 残余盲区（如实，不解决）

- `import hermes_tools as ht` 别名导入仍可绕过静态检测——同为"防糊涂不防执意"边界
- 业务 clarify 若把选项原文写成含「按此方案执行」字样，仍会被认作闸门卡（与出卡契约一致，代价可控）

### 验收

`scripts/test_gate.py` 新增 4 条断言 + 3 类拦截样本：业务卡回答"好"→零分类且不解锁；hermes_tools 导入 write_file / 属性 patch / 导入 terminal 三种形态必拦；hermes_tools 只读助手（read_file / search_files）必放。

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