#!/usr/bin/env python3
"""write-gate v1.1.3 离线验收：黑名单必拦 + 只读必放 + subprocess 注入必拦 + 解锁回归。

样本来源：2026-10-07 HermesSrv8119 修复会话的真实调用串，及近 7 天 terminal 高频命令。
EncodedCommand 盲区样本单独列出、不作通过断言（README 已知边界）。
用法：python scripts/test_gate.py   （退出码 0 = 全部通过）
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location("write_gate", os.path.join(PKG, "__init__.py"))
wg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wg)

NSSM = r"D:\AI_agent_workspace\main\hermes_serve_service\nssm-2.24\win64\nssm.exe"

# ── terminal：必须拦 ────────────────────────────────────────────────
TERM_BLOCK = [
    ("服务启动", "net start HermesSrv8119"),
    ("服务停止", "net stop HermesSrv8119"),
    ("sc 配置", 'sc.exe config HermesSrv8119 start= auto'),
    ("sc 删除", "sc delete FooSvc"),
    ("nssm 改参", f'{NSSM} set HermesSrv8119 Application C:\\Windows\\System32\\cmd.exe'),
    ("nssm 卸载", f'{NSSM} remove HermesSrv8119 confirm'),
    ("杀进程", "taskkill //F //IM hermes.exe"),
    ("计划任务创建", "schtasks /create /tn Hack /tr cmd"),
    ("注册表写", "reg add HKCU\\Software\\Foo /v x /d y"),
    ("POSIX 删除", "rm -rf D:\\tmp\\junk"),
    ("POSIX 移动", "mv a.txt b.txt"),
    ("Remove-Item", 'powershell -NoProfile -Command "Remove-Item C:\\temp\\x -Recurse"'),
    ("git push", "git push origin main"),
    ("git commit", 'git commit -m "feat: x"'),
    ("Set-Service", 'powershell -Command "Set-Service HermesSrv8119 -StartupType Automatic"'),
    ("Restart-Computer", "Restart-Computer -Force"),
    ("包安装", "winget install 7zip.7zip"),
    ("pip 安装", "pip install requests"),
    ("hermes 更新", "hermes update"),
    ("wmic 变更", 'wmic process call create "cmd.exe"'),
    ("串联躲首词", "ls -la && rm -rf /tmp/x"),
    ("管道后段变更", "echo hi | taskkill /F /PID 123"),
    ("PowerShell 全树杀", "Get-Process mmc | Stop-Process -Force"),
    ("任务计划注册", "Register-ScheduledTask -TaskName X -Action $a"),
    # v1.1.3：大小写一致性（Windows 命令不区分大小写；旧版第 5 类与 git 类漏 re.I）
    ("git 全大写", "GIT PUSH origin main"),
    ("cmd 大写 DEL", "DEL /f C:\\tmp\\x"),
    ("cmd 大写 REN", "REN a.txt b.txt"),
    ("PS 别名大写 RM", 'powershell -NoProfile -Command "RM C:\\tmp\\x"'),
    # v1.1.3：探查降级不再当危险命令的免检通行证
    ("删除尾挂 --help", "rm -rf D:\\tmp\\junk --help"),
    ("杀进程尾挂 /?", "taskkill /F /IM hermes.exe /?"),
    ("注册表写尾挂 --help", "reg add HKCU\\Software\\Foo /v x /d y --help"),
    ("停服务尾挂 -h", "net stop HermesSrv8119 -h"),
    # v1.1.3：PowerShell 写文件/写值 cmdlet（旧名词表里一条都不中）
    ("Set-Content", 'powershell -NoProfile -Command "Set-Content -Path a.txt -Value x"'),
    ("Out-File", 'powershell -NoProfile -Command "Get-Date | Out-File a.txt"'),
    ("Add-Content", 'powershell -NoProfile -Command "Add-Content a.txt x"'),
    ("Tee-Object", 'powershell -NoProfile -Command "Get-Process | Tee-Object -FilePath a.txt"'),
    ("Set-ItemProperty", 'powershell -NoProfile -Command "Set-ItemProperty -Path HKCU:\\X -Name y -Value 1"'),
]

# ── terminal：必须放（近 7 天真实只读形态）─────────────────────────
TERM_PASS = [
    ("目录切换", "cd /d D:\\AI_agent_workspace && dir"),
    ("服务查询", "powershell -NoProfile -Command \"Get-Service HermesSrv8119 | Format-List Name,Status\""),
    ("sc 查询", "sc.exe query HermesSrv8119"),
    ("nssm 只读", f'{NSSM} get HermesSrv8119 Application'),
    ("nssm status", f'{NSSM} status HermesSrv8119'),
    ("端口检查", "netstat -ano -p tcp"),
    ("进程列表", "tasklist"),
    ("git 状态", "git status -sb"),
    ("git 历史", "git log --oneline -15"),
    ("git diff", "git diff HEAD"),
    ("serve 运行", "hermes serve --host 100.126.149.100 --port 8119"),
    ("版本", "hermes --version"),
    ("接口探测", "curl -s http://100.126.149.100:8119/api/health"),
    ("任务查询", "schtasks /query /tn Foo"),
    ("wmic 只读", "wmic process list brief"),
    ("pip 列表", "pip list"),
    ("npm 脚本", "npm run build"),
    ("分析重定向", "python analyze.py > report.txt"),
    ("grep 过滤", "ls -la | grep foo"),
    ("EncodedCommand 外层", "powershell -NoProfile -EncodedCommand QQBhAGsA"),
    ("只读 PS", "powershell -NoProfile -Command \"Test-Path C:\\Users\\12; Get-Item C:\\x | Select-Object Length\""),
    ("变更命令探参数（回放误伤修复）", "hermes gateway install --help 2>&1 || true"),
    ("包安装探参数", "pip install requests --help"),
    # v1.1.3：可降级类目的探参数仍免检；只读脚本不得被新名词表误伤
    ("git 写操作探参数", "git commit --help"),
    ("PS 只读构造对象", 'powershell -NoProfile -Command "$o = New-Object PSObject"'),
    ("PS 读文件", 'powershell -NoProfile -Command "Get-Content a.txt"'),
    ("大小写只读", "TaskList /FO CSV"),
]

# ── terminal：必须拦（探查降级不可被骗——标志后面还有真实操作数/前段有变更）──
TERM_BLOCK_PROBE_TRICK = [
    ("串联藏变更", "rm -rf x && true --help"),
    ("分号后探查救不了前段", "git commit -A; echo --help"),
    ("真变更不带标志", "hermes gateway install"),
]

# ── execute_code：必须拦（今天踩的绕行路线 + 原文件写）──────────────
EXEC_BLOCK = [
    ("文件写 open", "f = open('out.txt', 'w')\nf.write('x')"),
    ("os 删除", "import os\nos.remove('C:/x/y.txt')"),
    ("subprocess 直调 nssm set", f"import subprocess\nr = subprocess.run([{NSSM!r}, 'set', 'HermesSrv8119', 'Application', 'C:\\\\Windows\\\\System32\\\\cmd.exe'], capture_output=True)"),
    ("subprocess shell taskkill", "import subprocess\nsubprocess.run('taskkill /F /PID 123', shell=True)"),
    ("subprocess 装包", "import subprocess\nsubprocess.run(['pip', 'install', 'requests'])"),
    ("subprocess net start", "import subprocess\nsubprocess.run('net start HermesSrv8119', shell=True)"),
    # v1.1.2：hermes_tools 程序化写助手（不经过工具层 pre_tool_call 钩子，2026-10-10 实测绕过）
    ("hermes_tools 导入 write_file", "from hermes_tools import write_file\nprint(write_file('a.txt', 'x'))"),
    ("hermes_tools 属性 patch", "import hermes_tools\nhermes_tools.patch('a.txt', 'old', 'new')"),
    ("hermes_tools 导入 terminal", "from hermes_tools import terminal\nterminal('rm -rf x')"),
    # v1.1.3：可写的"读改"模式（旧字符类 [wax] 漏判）
    ("open r+ 读改模式", "f = open('a.txt', 'r+')"),
    ("open r+b 读改模式", "f = open('a.txt', 'r+b')"),
    ("open rb+ 变体顺序", "f = open('a.txt', 'rb+')"),
]

# ── execute_code：必须放（只读分析形态）────────────────────────────
EXEC_PASS = [
    ("subprocess 查询", "import subprocess\nr = subprocess.run(['sc.exe','query','HermesSrv8119'], capture_output=True)"),
    ("subprocess nssm get", f"import subprocess\nsubprocess.run([{NSSM!r}, 'get', 'HermesSrv8119', 'Application'])"),
    ("subprocess netstat", "import subprocess\nr = subprocess.run(['netstat','-ano','-p','tcp'])"),
    ("纯分析", "import json\nprint(json.loads('{}'))"),
    ("read 模式", "data = open('in.txt').read()\nprint(data)"),
    ("hashlib", "import hashlib\nprint(hashlib.sha256(b'x').hexdigest())"),
    ("sqlite 只读", "import sqlite3\ncon = sqlite3.connect('file:x.db?mode=ro', uri=True)\nprint(con.execute('select 1').fetchone())"),
    # v1.1.2：hermes_tools 只读助手不受影响
    ("hermes_tools 只读 read_file", "from hermes_tools import read_file\nprint(read_file('a.txt'))"),
    ("hermes_tools 只读 search_files", "from hermes_tools import search_files\nprint(search_files('x'))"),
    # v1.1.3：只读模式不得被写模式扩展误伤
    ("open r 显式只读", "data = open('in.txt', 'r').read()\nprint(data)"),
    ("open rb 只读二进制", "data = open('in.bin', 'rb').read()\nprint(data)"),
]

fails = 0
total = 0

def check(label, got, want):
    global fails, total
    total += 1
    if got != want:
        fails += 1
        print(f"FAIL {label}: want={'block' if want else 'pass'} got={'block' if got else 'pass'}")

for label, cmd in TERM_BLOCK:
    check(f"term-block {label}", wg._terminal_is_write(cmd), True)
for label, cmd in TERM_BLOCK_PROBE_TRICK:
    check(f"term-block {label}", wg._terminal_is_write(cmd), True)
for label, cmd in TERM_PASS:
    check(f"term-pass  {label}", wg._terminal_is_write(cmd), False)
for label, code in EXEC_BLOCK:
    check(f"exec-block {label}", wg._exec_is_write({"code": code}), True)
for label, code in EXEC_PASS:
    check(f"exec-pass  {label}", wg._exec_is_write({"code": code}), False)

# ── 盲区记录（不作断言，如实打印）────────────────────────────────
blind = "powershell -NoProfile -EncodedCommand " + "AAA=" * 40  # 真实 nssm set 藏在这个 blob 里
blind_hit = wg._terminal_is_write(blind)
print(f"[盲区如实] EncodedCommand 载荷: terminal 判定={'拦' if blind_hit else '放'}（预期 放——载荷内容不可见，README 已知边界）")

# ── 解锁回归：锁定 block → 本轮放行 → 下轮重锁 ───────────────────
wg._exempt = lambda sid: False          # 离线模拟桌面锁定态
sid, t1, t2 = "s-test", "turn-1", "turn-2"
r1 = wg._on_pre_tool_call("terminal", {"command": "net start X"}, sid, t1)
assert r1 and r1["action"] == "block", "锁定态危险命令应 block"
wg._unlock[sid] = ("turn", t1)          # 模拟点「按此方案执行」
r2 = wg._on_pre_tool_call("terminal", {"command": "net start X"}, sid, t1)
r3 = wg._on_pre_tool_call("terminal", {"command": "ls -la"}, sid, t1)
assert r2 is None and r3 is None, "本轮解锁后写入/命令应静默放行"
r4 = wg._on_pre_tool_call("terminal", {"command": "net start X"}, sid, t2)
assert r4 and r4["action"] == "block", "下一条消息（新 turn）应重新锁定"

# ── v1.1.1：解锁/短路路径机械判定（_classify 调用次数断言）───────────
import json as _json, io, contextlib
_calls = []
class _FakeLLM:
    def complete_structured(self, **kw):
        _calls.append(kw)
        class R: parsed = {"switch": "TURN"}
        return R()
wg._LLM = _FakeLLM()
wg._exempt = lambda sid: False

def _clarify_result(resp, choices=None):
    return _json.dumps({"responses": [{"question": "q", "user_response": resp,
                                        "choices_offered": choices or ["按此方案执行", "取消"], "status": "answered"}]})

def _post(resp, sid, tid, choices=None):
    _calls.clear()
    with contextlib.redirect_stdout(io.StringIO()):
        wg._on_post_tool_call("clarify", _clarify_result(resp, choices), sid, tid)
    return len(_calls)

s, t1 = "s-v111", "t-1"
# ① 点标准批准：机械放行，零分类
n = _post("按此方案执行", s, t1)
check("unlock-no-classify", (n == 0 and wg._unlock.get(s, (None,))[0] == "turn"), True)
# ② 点取消：机械 NO 短路，零分类、不解锁
s2, t2 = "s-v111b", "t-2"
n = _post("取消", s2, t2)
check("cancel-mech-zero-llm", (n == 0 and s2 not in wg._unlock), True)
# ③ 自由文本意见：恰好一次分类（走 approval 任务槽）
s3, t3 = "s-v111c", "t-3"
n = _post("先把X改成Y再做", s3, t3)
check("free-text-one-classify", (n == 1 and _calls and _calls[0].get("task") == "approval"), True)

# ── v1.1.2：业务提问的 clarify 不得开闸（选项不含「按此方案执行」）────
s4, t4 = "s-v112-biz", "t-4"
n = _post("好，就这样", s4, t4, choices=["写入直接成功，我没见过卡", "见过卡但还被拦"])
check("biz-card-no-unlock-no-classify", (n == 0 and s4 not in wg._unlock), True)

# ── v1.1.3：机械放行收紧为精确匹配 ───────────────────────────────
class _NoLLM:
    def complete_structured(self, **kw):
        _calls.append(kw)
        class R: parsed = {"switch": "NO"}
        return R()

wg._LLM = _NoLLM()
# ④ 卡内"引用"选项发问：不得再走机械放行（旧版 startswith 会直接开闸）
s5, t5 = "s-v113-quote", "t-5"
n = _post("按此方案执行是什么意思？", s5, t5)
check("quote-question-not-mech-unlock", (n == 1 and s5 not in wg._unlock), True)
# ⑤ 点带括号后缀的闸门卡选项：仍须机械放行、零分类（收紧不得误伤正常点击）
s6, t6 = "s-v113-paren", "t-6"
n = _post("按此方案执行（重写操作卡模板）", s6, t6,
          choices=["按此方案执行（重写操作卡模板）", "取消"])
check("paren-option-click-still-unlocks", (n == 0 and wg._unlock.get(s6, (None,))[0] == "turn"), True)

# ── v1.1.6：改动行数阈值 + 第 5 条并发占用 ─────────────────────
import tempfile

class _Cfg:
    def __init__(self, sw=True, lines=0):
        self.sw, self.lines = sw, lines
    def get_config(self, k, d=None):
        return {"delegate_after_approval": self.sw, "delegate_min_lines": self.lines}.get(k, d)

wg._exempt = lambda sid: False

def _pre(tool, args, sid, tid):
    return wg._on_pre_tool_call(tool_name=tool, args=args, session_id=sid, turn_id=tid)

def _arm(sw, lines, sid="s-thr", tid="t-thr"):
    wg._CTX = _Cfg(sw, lines)
    wg._unlock.clear(); wg._redirected.clear(); wg._cwd_cache.clear(); wg._changed_acc.clear()
    wg._unlock[sid] = ("turn", tid)
    return sid, tid

D = wg._DELEGATE_MSG
one_line_patch = {"path": "x.py", "old_string": "a\n", "new_string": "b\n"}
many_line_patch = {"path": "x.py", "old_string": "a\n", "new_string": "".join("L%d\n" % i for i in range(12))}

s, t_ = _arm(True, 10)
check("thr-patch-1line-direct", _pre("patch", one_line_patch, s, t_) is None, True)

s, t_ = _arm(True, 10)
check("thr-patch-12lines-delegate", _pre("patch", many_line_patch, s, t_) == {"action": "block", "message": D}, True)

s, t_ = _arm(True, 0)
check("thr-zero-means-all-delegate", _pre("patch", one_line_patch, s, t_) == {"action": "block", "message": D}, True)

s, t_ = _arm(True, 10)
check("thr-writefile-new-small-direct",
      _pre("write_file", {"path": "C:/__wg_no_such__/n.txt", "content": "a\nb\nc\n"}, s, t_) is None, True)

s, t_ = _arm(True, 10)
check("thr-terminal-unknown-delegate",
      _pre("terminal", {"command": "git push origin main"}, s, t_) == {"action": "block", "message": D}, True)

s, t_ = _arm(True, 10)
check("thr-exec-unknown-delegate",
      _pre("execute_code", {"code": "from hermes_tools import write_file\nwrite_file(p, c)"}, s, t_)
      == {"action": "block", "message": D}, True)

s, t_ = _arm(True, 10)
check("thr-patch-no-new-string-delegate",
      _pre("patch", {"path": "x.py", "mode": "patch", "input": "*** Begin Patch"}, s, t_)
      == {"action": "block", "message": D}, True)

with tempfile.TemporaryDirectory() as td:
    fp = os.path.join(td, "big.txt")
    base = ["line %d" % i for i in range(100)]
    with open(fp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(base) + "\n")
    one = list(base); one[50] = "line 50 CHANGED"
    s, t_ = _arm(True, 10)
    check("thr-writefile-abs-1line-direct",
          _pre("write_file", {"path": fp, "content": "\n".join(one) + "\n"}, s, t_) is None, True)
    many = ["new %d" % i for i in range(20)] + base[20:]
    s, t_ = _arm(True, 10)
    check("thr-writefile-abs-20lines-delegate",
          _pre("write_file", {"path": fp, "content": "\n".join(many) + "\n"}, s, t_)
          == {"action": "block", "message": D}, True)
    s, t_ = _arm(True, 10)
    wg._cwd_cache[s] = (td, wg._now())
    check("thr-writefile-relative-cwd-1line-direct",
          _pre("write_file", {"path": "big.txt", "content": "\n".join(one) + "\n"}, s, t_) is None, True)

s, t_ = _arm(True, 10)
check("thr-memory-never-delegates", _pre("memory", {}, s, t_) is None, True)
s, t_ = _arm(True, 10)
wg._unlock[s] = ("session", t_)
check("thr-session-scope-never-delegates", _pre("patch", one_line_patch, s, t_) is None, True)

s, t_ = _arm(True, 10)
_pre("patch", many_line_patch, s, t_)
check("thr-retry-same-turn-still-delegates",
      _pre("patch", many_line_patch, s, t_) == {"action": "block", "message": D}, True)

# 方案 B：本轮不放行 → 重试不能绕过；换 turn 后 _unlock 失效 = 回到"未确认"
s, t_ = _arm(True, 10)
_pre("patch", many_line_patch, s, t_)
check("thr-new-turn-relocks",
      _pre("patch", many_line_patch, s, "t-next") == {"action": "block", "message": wg._BLOCK_MSG}, True)

# 按轮累计（v1.1.7）：同轮 12+12 ≥ 20 → 第二次转派；换 turn 清零后仍直写
s, t_ = _arm(True, 20)
r1 = _pre("patch", many_line_patch, s, t_)
r2 = _pre("patch", many_line_patch, s, t_)
check("acc-second-call-delegates", (r1 is None and r2 == {"action": "block", "message": D}), True)

s, t_ = _arm(True, 20)
_pre("patch", many_line_patch, s, t_)
wg._changed_acc[s] = ("other-turn", 12)
check("acc-resets-on-new-turn", _pre("patch", many_line_patch, s, t_) is None, True)

# 纯删除也算改动量：删 1 行直写、删 25 行转派（v1.1.7 修）
del1 = {"path": "x.py", "old_string": "abc", "new_string": ""}
del25 = {"path": "x.py", "old_string": "".join("D%d" % i + chr(10) for i in range(25)), "new_string": ""}

s, t_ = _arm(True, 20)
check("del-1line-direct", _pre("patch", del1, s, t_) is None, True)

s, t_ = _arm(True, 20)
check("del-25lines-delegate", _pre("patch", del25, s, t_) == {"action": "block", "message": D}, True)

# 阈值边界：不超过阈值就直写（等于也直写），多 1 行才转派
exact20 = {"path": "x.py", "old_string": "a", "new_string": "".join("E%d" % i + chr(10) for i in range(20))}
over21 = {"path": "x.py", "old_string": "a", "new_string": "".join("F%d" % i + chr(10) for i in range(21))}

s, t_ = _arm(True, 20)
check("thr-exactly-at-limit-direct", _pre("patch", exact20, s, t_) is None, True)

s, t_ = _arm(True, 20)
check("thr-one-over-limit-delegates", _pre("patch", over21, s, t_) == {"action": "block", "message": D}, True)

check("msg-item5-concurrency-clause",
      ("delegate_task(action='list')" in D and "文件不重合的独立新活 → 新派" in D
       and "改动文件与它手上的重合" in D and "拿不准就 steer" in D
       and "不要让它 sleep 或轮询" in D
       and "临时文件只写 TMPDIR" in D), True)
check("msg-items-1to4-intact",
      ("1) 不要重试本调用" in D and "4) 子代理的回报如实转述" in D), True)

print(f"\n断言总数: {total}, 失败: {fails}")
sys.exit(1 if fails else 0)
