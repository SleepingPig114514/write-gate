#!/usr/bin/env python3
"""write-gate v1.1.0 离线验收：黑名单必拦 + 只读必放 + subprocess 注入必拦 + 解锁回归。

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
]

# ── execute_code：必须拦（今天踩的绕行路线 + 原文件写）──────────────
EXEC_BLOCK = [
    ("文件写 open", "f = open('out.txt', 'w')\nf.write('x')"),
    ("os 删除", "import os\nos.remove('C:/x/y.txt')"),
    ("subprocess 直调 nssm set", f"import subprocess\nr = subprocess.run([{NSSM!r}, 'set', 'HermesSrv8119', 'Application', 'C:\\\\Windows\\\\System32\\\\cmd.exe'], capture_output=True)"),
    ("subprocess shell taskkill", "import subprocess\nsubprocess.run('taskkill /F /PID 123', shell=True)"),
    ("subprocess 装包", "import subprocess\nsubprocess.run(['pip', 'install', 'requests'])"),
    ("subprocess net start", "import subprocess\nsubprocess.run('net start HermesSrv8119', shell=True)"),
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
]

fails = 0

def check(label, got, want):
    global fails
    if got != want:
        fails += 1
        print(f"FAIL {label}: want={'block' if want else 'pass'} got={'block' if got else 'pass'}")

for label, cmd in TERM_BLOCK:
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

print(f"\n断言总数: {len(TERM_BLOCK)+len(TERM_PASS)+len(EXEC_BLOCK)+len(EXEC_PASS)+4}, 失败: {fails}")
sys.exit(1 if fails else 0)
