"""write-gate — 确认闸门（没按过按钮就不许写/改状态）。

插件的唯一职责：动工前给用户一个按钮。三级确认范围：
  · 单次回复（默认）：点「按此方案执行」→ 本轮 agent 运行内全部写入静默；
    用户下一条消息（新 turn_id）起自动重新锁定；
  · 单次会话：确认卡自定义框表达"这个会话都别问了" → 会话级放行，
    反悔方式 = 重启或新开会话（解锁态纯内存，新会话天然锁定）；
  · 所有会话：设置→插件 页拨 write-gate 开关。
  · 转派子代理（默认关，「能力→插件」页开关）：打开后点「按此方案执行」不再由主模型
    重试写入，而是拦下本次调用、由模型派 delegate_task 执行；同一轮再次重试则直接放行
    （宁可退化不死锁）。改动行数低于 settings.delegate_min_lines 时直写、不转派。
不判定路径、不设时间窗、不维护白名单——范围与计划是模型和用户之间的事。

拦截 write_file / patch / memory / execute_code(代码含写模式或状态变更) /
terminal(命令命中状态变更黑名单)：
锁定状态下发起一律 block，指示模型「正文呈现方案 → 调 clarify 出确认卡」。
terminal 走黑名单方向：默认放行，仅命中 _STATE_PATTERNS 才拦（防糊涂不防执意；
漏判退回无闸门状态，误判代价 = 多弹一张卡）。
fail-open：本插件任何内部异常都放行（最坏退回无闸门状态，不卡死会话）。
豁免：无确认卡 UI 的来源（cron/oneshot/qqbot/unknown）、delegation 子会话；
交互来源（desktop/local/gui/tui）一律进闸门——2026-10-27 起桌面端会话来源变成 local，
原来的「不等于 desktop 就豁免」让桌面会话全部被静默放过。
（clarify 被禁用，防死锁）、环境变量 WRITE_GATE=off、后台自我改进回顾的 memory 写入
（review fork 与主会话共享 session_id，按来源判据识别不出来，clarify 又不在其白名单；
上游 memory_tool 自带 _background_delete_gate，负责把 patch/remove 转 pending 待批）。
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

APPROVE_LABEL = "按此方案执行"
_MANAGED = ("write_file", "patch", "memory", "execute_code", "terminal")

_LOCK = threading.Lock()
# session_id -> (scope, turn_id)；scope ∈ {"turn","session"}
_unlock: Dict[str, Tuple[str, str]] = {}
_source_cache: Dict[str, tuple] = {}         # session_id -> (source, parent, ts)
# session_id -> turn_id：本轮已把「已批准的写入」导向 delegate_task 一次。
# 只认当前 turn（turn 变了自然失效）；命中即放行 = 兜底，宁可退化不肯死锁。
_redirected: Dict[str, str] = {}
_cwd_cache: Dict[str, tuple] = {}            # session_id -> (cwd, ts)  相对路径解析用
_changed_acc: Dict[str, tuple] = {}          # session_id -> (turn_id, 本轮累计改动行数)
_READ_LIMIT = 2 * 1024 * 1024                # 算真实改动量时最多读这么多字节，超了按全文行数

# execute_code 文件写模式：命中任一即视为写操作。防糊涂不防执意（README 有言在先）。
_WRITE_PATTERNS = [
    # v1.1.3 修：旧字符类 [wax][+btu]* 只认 w/a/x 开头的模式，漏了 open(f,'r+') / ('r+b')
    # 这类"读改"可写模式；补 (?:[rbtu]*[wax][+btu]*|[rbtu]*\+[btu]*) 分支，只读 r/rb/rt 仍放行
    re.compile(r"\bopen\s*\([^)]{0,200}?['\"](?:[rbtu]*[wax][+btu]*|[rbtu]*\+[btu]*)['\"]"),
    re.compile(r"\bshutil\.(copy\w*|move|rmtree|remove|unlink)\b"),
    re.compile(r"\bos\.(remove|unlink|rename|replace|makedirs?|rmdir|truncate)\b"),
    re.compile(r"\.write_text\s*\(|\.write_bytes\s*\(|\.touch\s*\(|\.mkdir\s*\(|\.unlink\s*\(|\.rename\s*\("),
    # 注：v1.0.0 此处字符类误写为 [>'>]（含撇号），会把任何带引号参数的 subprocess 调用误判为重定向写；1.1.0 修正为纯重定向检测，状态变更判定改由 _STATE_PATTERNS blob 扫描承担
    re.compile(r"\bsubprocess\.\w+\b[^#\n]*>{1,2}\s*\S"),
    # hermes_tools 程序化助手（v1.1.2 补）：execute_code 内 from hermes_tools import
    # write_file / patch / terminal 会绕过工具层 pre_tool_call 钩子直接落盘——2026-10-10
    # 实测确认（锁定态下 execute_code 内 write_file 写盘成功，同轮直接 write_file 被拦）。
    # 按静态形态兜住直接调用；别名导入（import hermes_tools as ht）仍是盲区，
    # 防糊涂不防执意，README「已知边界」已记。
    re.compile(r"\bfrom\s+hermes_tools\b[\s\S]{0,160}?\b(?:write_file|patch|terminal)\b"),
    re.compile(r"\bhermes_tools\s*\.\s*(?:write_file|patch|terminal)\b"),
]

# ── 状态变更黑名单（terminal 与 execute_code 内 subprocess 共用，v1.1.0）──────
# 方向性契约：默认放行、命中才拦。漏判 = 退回无闸门（不恶化）；误判 = 多弹一卡。
# 扩充原则：只在真实漏判发生后补条目，条目须写明拦什么/放什么，防误伤扩散。
# 每条 = (正则, 可否被探参数降级)：可降级 = 该段尾挂 --help/-h/--dry-run/? 时免检。
# 仅"可重复、可回滚、且 CLI 遇 --help 先打印帮助退出"的类目可降级（包安装/包管理/
# hermes 自身/git 写操作）；删除、杀进程、服务停止、注册表写、文件系统变更、wmic、
# PowerShell 变更动词一律不可降级——v1.1.3 修：旧版对任何段一律免检，危险命令尾部挂
# 一个 --help 即可整段绕过闸门。大小写：Windows 命令不区分大小写（cmd/PowerShell 别名、
# GIT/DEL），除有明确理由者外一律带 re.I——v1.1.3 修：第 5 类与 git 类曾漏 re.I。
_STATE_PATTERNS: List[Tuple[re.Pattern, bool]] = [
    # 1 服务/系统状态：net/sc 变更子命令（查询类 sc query、netstat 不拦）；
    #   nssm 需 60 字符内带变更动词（nssm get/status 只读不拦）——停服不可逆，不降级
    (re.compile(r"\b(?:net|sc(?:\.exe)?)\s+(?:start|stop|delete|create|config|pause|continue)\b", re.I), False),
    (re.compile(r"\bnssm\b[\s\S]{0,60}?\b(?:set|install|remove|start|stop|restart|pause|continue)\b", re.I), False),
    # 2 计划任务：创建/删除/修改；Query 不拦——不降级
    (re.compile(r"\bschtasks\s+/(?:create|delete|change)\b", re.I), False),
    (re.compile(r"\b(?:Register-|Unregister-|Set-)ScheduledTask\b", re.I), False),
    # 3 杀进程（高危不可逆）；tasklist 只读不在列——不降级
    (re.compile(r"\btaskkill\b", re.I), False),
    # 4 注册表写入；reg query 不拦——不降级
    (re.compile(r"\breg(?:\.exe)?\s+(?:add|delete|import|restore|load|unload)\b", re.I), False),
    # 5 文件系统变更（POSIX 与 cmd/PowerShell 形态；须带参数，孤立词不算）——不降级
    (re.compile(r"\b(?:rm|rmdir|del|erase|ren|unlink)\s+\S", re.I), False),
    (re.compile(r"\b(?:mv|cp)\s+(?:-{1,2}\w+\s+)*\S+\s+\S+", re.I), False),
    (re.compile(r"\bremove[\s_\-]*(?:item|file)\b", re.I), False),
    # 6 安装/包管理——可降级（可重复、可回滚；`pip install x --help` 是读文档常态）
    (re.compile(r"\b(?:winget|choco)\s+(?:install|uninstall|update|upgrade)\b", re.I), True),
    (re.compile(r"\b(?:npm|pnpm|yarn|pip|pip3|uv|cargo)\s+(?:install|uninstall|add|remove|update)\b", re.I), True),
    (re.compile(r"\binstall[\s_\-]*package\b", re.I), True),
    # 7 git 写操作（提交/推送/改写工作区）；status/log/diff 只读不拦——可降级
    (re.compile(r"\bgit\s+(?:push|commit|checkout|restore|reset|clean|merge|rebase|stash|apply|tag)\b", re.I), True),
    # 8 PowerShell 变更动词（cmdlet 形态；大写不敏感，兼容无连字符直调变体；
    #   仅对系统对象生效——Set-Location/Get-* 类导航读取不拦）；v1.1.3 补写文件/写值的
    #   名词（Content/Csv/ItemProperty）与动词（Export），并单独兜 Out-/Tee- 系：
    #   Set-Content / Add-Content / Set-ItemProperty / Export-Csv / Out-File / Tee-Object
    #   此前一条都不中。刻意不含 Object 名词——New-Object 是纯内存构造，不该误伤只读脚本。
    (re.compile(
        r"\b(?:Set|New|Remove|Stop|Restart|Install|Uninstall|Disable|Enable|Add|Clear|"
        r"Move|Copy|Rename|Format|Export)[\s_\-]*(?:Service|Item|ItemProperty|File|Content|"
        r"Csv|Process|Computer|Machine|Registry|"
        r"Package|Scheduled[A-Za-z]*|Firewall|NetAdapter|Route|Task|User|LocalUser|"
        r"Volume|Disk|Partition|ExecutionPolicy)\b", re.I), False),
    (re.compile(r"\b(?:Out|Tee)[\s_\-]*(?:File|Object|Csv)\b", re.I), False),
    (re.compile(r"\brestart[\s_\-]*computer\b", re.I), False),
    # 9 wmic 变更子命令；list/get 只读不拦——不降级
    (re.compile(r"\bwmic\b[^\n]*\b(?:modify|call|create|delete)\b", re.I), False),
    # 10 Hermes 自身变更子命令（改本机安装/配置/注册状态）；--version、status、serve 不拦
    #    ——可降级（`hermes gateway install --help` 是探参数常态）
    (re.compile(r"\bhermes\s+(?:update|install|uninstall|gateway\s+install|config\s+set"
                r"|cron\s+(?:add|remove|edit)|skills?\s+(?:add|remove|install)"
                r"|computer-use\s+install|vault\s+add)\b", re.I), True),
]

# 拆段：管道/串联命令逐段检查，防 "ls && rm -rf x" 躲过首词判定。
# 已知简化：不感知引号内分隔符——引号里含 && 的命令罕见，误伤代价仅多弹一卡。
_SEGMENT_SPLIT_RX = re.compile(r"&&|\|\||[;\n|]")
# subprocess 调用抽取（括号配平，见 _subprocess_blobs）
_SUBPROC_CALL_RX = re.compile(r"\bsubprocess\.\w+\s*\(")
_STR_LIT_RX = re.compile(r"'([^']*)'|\"([^\"]*)\"")

# 探查降级：段带 --help/-h/--dry-run/? 类只读探查标志，且标志之后不再跟真实操作数
# （只剩 2>&1 类重定向碎片）时，该段内的"可降级"条目免检——"hermes gateway install
# --help" 这种探参数不该拦。v1.1.3 修：降级按条目白名单（见 _STATE_PATTERNS 第二字段），
# 只有包安装/包管理/hermes 自身/git 写操作四类可降级；删除、杀进程、服务停止、注册表写、
# 文件系统变更一律不可降级——旧版整段免检时 `rm -rf <path> --help` 一行即绕过闸门。
_PROBE_FLAG_RX = re.compile(r"(?:^|\s)(?:--help|-h|--dry-run|/\?|\?)(?=\s|$)")
_PROBE_JUNK_RX = re.compile(r"^[\d<>]")


def _segment_is_probe(seg: str) -> bool:
    m = _PROBE_FLAG_RX.search(seg)
    if not m:
        return False
    rest = seg[m.end():].split()
    return all(_PROBE_JUNK_RX.match(t) for t in rest)


def _segments(cmd: str) -> List[str]:
    return [s for s in _SEGMENT_SPLIT_RX.split(cmd) if s.strip()]


def _hit_state(text: str) -> bool:
    """段逐一比对黑名单；探参数降级只对标记"可降级"的条目生效（v1.1.3）。"""
    for seg in _segments(text):
        probe = _segment_is_probe(seg)
        for rx, degradable in _STATE_PATTERNS:
            if rx.search(seg) and not (probe and degradable):
                return True
    return False


def _terminal_is_write(command: str) -> bool:
    """terminal 命令段逐一比对黑名单；命中任一段即算状态变更。"""
    if not isinstance(command, str):
        return False
    return _hit_state(command)


def _subprocess_blobs(code: str) -> List[str]:
    """抽取代码里每个 subprocess 调用的参数文本（括号配平，容忍字符串）。"""
    blobs = []
    for m in _SUBPROC_CALL_RX.finditer(code):
        i, depth, instr, out = m.end(), 1, None, []
        n = len(code)
        while i < n and depth > 0:
            ch = code[i]
            if instr:
                out.append(ch)
                if ch == "\\":
                    out.append(code[i + 1] if i + 1 < n else "")
                    i += 2
                    continue
                if ch == instr:
                    instr = None
            elif ch in "\"'":
                instr = ch
                out.append(ch)
            elif ch == "(":
                depth += 1
                out.append(ch)
            elif ch == ")":
                depth -= 1
                if depth > 0:
                    out.append(ch)
            else:
                out.append(ch)
            i += 1
        blobs.append("".join(out))
    return blobs


def _unquote_join(blob: str) -> str:
    """字符串字面量内容还原成单行文本（覆盖 list 形参把命令拆成碎片的情况）。"""
    parts = []
    for a, b in _STR_LIT_RX.findall(blob):
        s = a or b
        if s.strip():
            parts.append(s)
    return " ".join(parts)


def _exec_is_write(args: Dict[str, Any]) -> bool:
    """execute_code：沿用文件写模式 + 扫 subprocess 参数里的状态变更命令。"""
    code = args.get("code") or ""
    if not isinstance(code, str):
        return False
    if any(rx.search(code) for rx in _WRITE_PATTERNS):
        return True
    for blob in _subprocess_blobs(code):
        if _hit_state(blob) or _hit_state(_unquote_join(blob)):
            return True
    return False


def _env_off() -> bool:
    return os.environ.get("WRITE_GATE", "").strip().lower() in {"off", "0", "no", "false"}


def _plugin_version() -> str:
    """从同目录 plugin.yaml 读版本号，只用于启动日志（读不到返回 "?"）。

    存在的意义：插件代码只在网关启动时装载，改完文件没重启时行为仍是旧的。
    启动日志里有版本号 + 目录，一眼就能判断"跑的是不是改过的那份"。
    """
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugin.yaml")
        with open(path, "r", encoding="utf-8-sig") as f:
            m = re.search(r'^version:\s*"?([\w.\-]+)', f.read(), re.M)
        return m.group(1) if m else "?"
    except Exception:
        return "?"


def _now() -> float:
    return time.time()


def _session_meta(session_id: str) -> tuple:
    """查 state.db 取 (source, parent_session_id)，缓存 60s。失败按 ('desktop','') 处理（fail-closed 进闸门）。"""
    cached = _source_cache.get(session_id)
    if cached and _now() - cached[2] < 60:
        return cached[0], cached[1]
    source, parent = "desktop", ""
    try:
        from hermes_constants import get_hermes_home
        db = str(get_hermes_home() / "state.db")
        import sqlite3
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1.0)
        try:
            row = con.execute("SELECT source, parent_session_id FROM sessions WHERE id=?", (session_id,)).fetchone()
            if row:
                source = (row[0] or "desktop").lower()
                parent = row[1] or ""
        finally:
            con.close()
    except Exception:
        pass  # 查不到就按桌面处理：宁可多拦不误放
    _source_cache[session_id] = (source, parent, _now())
    return source, parent


_INTERACTIVE_SOURCES = {"desktop", "local", "gui", "tui"}


def _exempt(session_id: str) -> bool:
    """非交互/无卡会话豁免：cron、oneshot、qqbot、unknown、子代理。

    判据用「正面白名单」而不是「不等于 desktop 就豁免」：
    2026-10-27 起桌面端改走本地网关通道，Hermes 把会话来源记成 `local`
    而不是 `desktop`，负面判据会让所有桌面会话被静默豁免（实测 10-27 之后
    闸门一次都没拦过）。交互来源（desktop/local/gui/tui）一律进闸门，
    只有确实没有确认卡 UI 的来源才豁免。
    """
    if _env_off():
        return True
    if not session_id:
        return True  # 拿不到会话身份，不猜——放行（fail-open）
    source, parent = _session_meta(session_id)
    return source not in _INTERACTIVE_SOURCES or bool(parent)


def _is_unattended_review() -> bool:
    """当前调用是否来自后台自我改进回顾（background review）的 fork。

    复用 Hermes 自带判据 tools.skill_provenance.is_unattended_review（contextvar），
    不另造识别逻辑。review fork 与主会话共享 session_id，_exempt 的来源判据对它无效。
    """
    try:
        from tools.skill_provenance import is_unattended_review
        return bool(is_unattended_review())
    except Exception:
        return False


def _is_write(tool_name: str, args: Dict[str, Any]) -> bool:
    """该调用是否落在受管写/状态变更操作上。"""
    if tool_name in ("write_file", "patch", "memory"):
        return True
    if tool_name == "execute_code":
        return _exec_is_write(args)
    if tool_name == "terminal":
        return _terminal_is_write(args.get("command") or "")
    return False


def _delegate_after_approval() -> bool:
    """「确认后自动转派子代理」开关（plugin.yaml config_schema → 桌面端 能力→插件 页）。

    每次调用现读 plugins.entries.write-gate.settings.delegate_after_approval，拨动后
    立即生效、不用重启网关。读不到/读失败一律按「关闭」处理——关闭态就是旧行为。
    """
    try:
        return bool(_CTX.get_config("delegate_after_approval", False))
    except Exception:
        return False


def _delegate_min_lines() -> int:
    """低于这个改动行数就直接写入、不转派；0 = 不设阈值（全部转派，v1.1.5 行为）。"""
    try:
        return max(0, int(_CTX.get_config("delegate_min_lines", 0) or 0))
    except Exception:
        return 0


def _session_cwd(session_id: str) -> str:
    """查 state.db 取会话工作目录（相对路径解析用），缓存 60s；拿不到返回 ""。"""
    cached = _cwd_cache.get(session_id)
    if cached and _now() - cached[1] < 60:
        return cached[0]
    cwd = ""
    try:
        from hermes_constants import get_hermes_home
        db = str(get_hermes_home() / "state.db")
        import sqlite3
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1.0)
        try:
            row = con.execute("SELECT cwd FROM sessions WHERE id=?", (session_id,)).fetchone()
            if row and row[0]:
                cwd = str(row[0])
        finally:
            con.close()
    except Exception:
        pass  # 查不到就当没有 cwd：相对路径回退到按全文行数算
    _cwd_cache[session_id] = (cwd, _now())
    return cwd


def _changed_lines(tool_name: str, args: Dict[str, Any], session_id: str = "") -> Optional[int]:
    """估算本次写入改动了多少行。None = 估不出（terminal / execute_code / 形态不明）。

    patch：new_string 的行数。
    write_file：目标存在且 <= _READ_LIMIT 时用 SequenceMatcher 比真实改动量（改 1 行 = 1）；
    相对路径先按会话 cwd 解析；读不到就退回 content 的全文行数。
    """
    try:
        if tool_name == "patch":
            if "new_string" not in args:
                return None          # V4A 多文件形态等：连键都没有，本次改多少无从判断
            new = args.get("new_string")
            if not isinstance(new, str):
                return None
            if new == "":
                # 纯删除：改动量 = 被删掉的行数（旧版把空串当"估不出"，删 1 行也会被转派）
                old = args.get("old_string")
                return max(1, len(old.splitlines())) if isinstance(old, str) and old else None
            return max(1, len(new.splitlines()))
        if tool_name != "write_file":
            return None
        content = args.get("content")
        if not isinstance(content, str):
            return None
        path = str(args.get("path") or "")
        if path and not os.path.isabs(path) and session_id:
            cwd = _session_cwd(session_id)
            if cwd:
                path = os.path.join(cwd, path)
        if path and os.path.isabs(path) and os.path.isfile(path) \
                and os.path.getsize(path) <= _READ_LIMIT:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                old = f.read()
            import difflib
            sm = difflib.SequenceMatcher(None, old.splitlines(), content.splitlines(), autojunk=False)
            return sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal")
        return len(content.splitlines())
    except Exception:
        return None


def _accumulated_below_threshold(tool_name: str, args: Dict[str, Any],
                                 session_id: str = "", turn_id: str = "") -> bool:
    """把本次改动累计进本轮，累计值不超过 delegate_min_lines 才直写（等于阈值也直写）。

    同轮多次写入会累加：零碎改 5 个文件、每次 15 行，第 2 次就越线转派（已落盘的
    前几次不回收）。估不出行数 / 未设阈值 / 已超线 → False（转派）。换 turn 自动清零。
    """
    limit = _delegate_min_lines()
    if limit <= 0:
        return False
    lines = _changed_lines(tool_name, args, session_id)
    if lines is None:
        return False
    with _LOCK:
        prev_turn, acc = _changed_acc.get(session_id, (turn_id, 0))
        if prev_turn != turn_id:
            acc = 0
        acc += lines
        _changed_acc[session_id] = (turn_id, acc)
    return acc <= limit


_BLOCK_MSG = (
    "[write-gate] 该写操作/命令未获用户确认，已被拦下（文件/记忆/系统状态未发生任何变化）。\n"
    "请严格按以下流程处理：\n"
    "1) 在回复正文向用户呈现方案：本次要执行的全部变更目标（路径级/命令级）、目的与步骤；\n"
    f"2) 调用 clarify 出执行确认卡：问题正文写明同意范围（目标文件/命令清单/边界），"
    f"选项恒为「{APPROVE_LABEL}」（放第一个）与「取消」两项；"
    "用户可在自定义框补充意见，意见由语义分类判范围，拿不准维持锁定；\n"
    "3) 卡片中注明：批准后本轮回复内不再询问，用户下一条消息起恢复确认；\n"
    "4) 用户批准后，重试本调用即自动放行；用户提出修改意见时，按意见更新方案后重新出卡，"
    "不要自行猜测放行。\n"
    "禁止：改用 terminal/其他通道绕过闸门；未获 clarify 批准前反复重试同一调用。"
    "被拦后向用户呈现方案并等待，本身就是合法的回合交付。"
)


_DELEGATE_MSG = (
    "[write-gate] 该写操作已获用户批准，但「确认后自动转派子代理」开关为开：本写入不由你执行。\n"
    "请严格按以下方式处理：\n"
    "1) 不要重试本调用，也不要改用 terminal/execute_code 或其他任何通道自己落盘；\n"
    "2) 用 delegate_task 执行这次已批准的方案（steer 还是新派，按第 5 条的执行顺序），brief 必须写清三段：\n"
    "   · 允许改的绝对路径清单（一个路径一行，逐个列全）；\n"
    "   · 禁止触碰范围：清单外的文件/目录一律不改，临时文件只写 TMPDIR 并收尾删除，不顺手重构、不格式化、不动无关内容；\n"
    "   · 回报要求：实际改了哪些文件，每个文件的最终字节数与 SHA256。\n"
    "3) 这次写入只执行一次：并进一条 steer，不要留到下一轮再说。\n"
    "4) 子代理的回报如实转述给用户（文件、字节数、哈希），不要替它补写未核实的结果。\n"
    "5) 执行顺序（照做，不跳步）：\n"
    "   ① 先 delegate_task(action='list')；\n"
    "   ② 有子代理在跑、且这次要动的文件在它正在改的文件里 → 用 action='steer' 把要求追加给它，\n"
    "      不新派、不等它回执；\n"
    "   ③ 你手上还有同批文件的活 → 继续 steer，一条一条加完再往下走；\n"
    "   ④ 没有可追加的子代理 → 新派一次，然后结束本轮。\n"
    "   追加多个任务时，每条 steer 开头写「做完你手上这件，接着做……」。\n"
    "   要读它正在写的文件，等它回执再读；不要让它 sleep 或轮询另一个子代理。\n"
    "   验收：追加的每一条都要在它最终回执里逐条对上，对不上 ＝ 未完成。\n"
    "说明：子代理会话不受本闸门拦截；本轮不再放行——重试同一写入只会再收到这份指令，"
    "直到本轮结束（下一轮重新上锁、需重新批准）。"
)


def _on_pre_tool_call(tool_name: str = "", args: Any = None, session_id: str = "",
                      turn_id: str = "", **_kw) -> Optional[Dict[str, str]]:
    try:
        if tool_name not in _MANAGED:
            return None
        if not isinstance(args, dict) or _exempt(session_id):
            return None
        # 后台回顾的 memory 写入交出控制权：它无法弹确认卡（clarify 不在其工具白名单），
        # 拦下等于把用户画像的自动更新链路整条堵死。上游 memory_tool 的
        # _background_delete_gate 已负责把 patch/remove 转 pending 待批、add 直接写入；
        # 此处只放 memory，write_file / patch / terminal 仍拦。
        if tool_name == "memory" and _is_unattended_review():
            return None
        if not _is_write(tool_name, args):
            return None
        with _LOCK:
            u = _unlock.get(session_id)
            unlocked = bool(u and (u[0] == "session" or (u[0] == "turn" and u[1] and u[1] == turn_id)))
            # 只有「按此方案执行」产生的单轮放行可转派：SESSION 级（用户说"别问了"）
            # 保持旧行为，否则那种会话会每条消息都派一个子代理。memory 不转派：
            # 子代理没有 memory 工具（工具层禁用），转过去必然空转。
            turn_scoped = bool(unlocked and u and u[0] == "turn" and turn_id
                               and tool_name != "memory")
            already = bool(turn_scoped and _redirected.get(session_id) == turn_id)
        if not unlocked:
            return {"action": "block", "message": _BLOCK_MSG}
        if turn_scoped and _delegate_after_approval():
            if already:
                # 本轮已转派过：不放行，重复同一份指令。重试不能把转派绕过去；
                # 下一轮 turn_id 变化后 _unlock 失效，重新回到"未确认"、需重新批准，
                # 所以不放行也不会死锁。
                return {"action": "block", "message": _DELEGATE_MSG}
            if not _accumulated_below_threshold(tool_name, args, session_id, turn_id):
                with _LOCK:
                    _redirected[session_id] = turn_id
                logger.info("write-gate: session %s redirecting approved %s to subagent (turn %s)",
                            session_id, tool_name, turn_id)
                return {"action": "block", "message": _DELEGATE_MSG}
        return None
    except Exception as err:                        # fail-open
        logger.warning("write-gate pre_tool_call error (pass-through): %s", err)
        return None


_CLASSIFY_INSTRUCTIONS = (
    "你是写操作确认闸门的范围识别器。闸门默认锁定（模型每次写入前弹卡确认）；"
    "用户回复可切换放行范围。下面是用户回复原文，判断意图，只输出 JSON：\n"
    'TURN=同意执行本次方案（如"好""可以""做吧""同意""按此方案执行"）——仅本轮放行；\n'
    "SESSION=要求本会话后续都不再逐次确认（如\"别问了\"\"这次会话都直接做\"\"以后这种不用再问\"）——整会话放行；\n"
    "NO=其余一切情况：提问、拒绝、部分修改意见、含糊表态——拿不准就选 NO。\n"
    '输出格式：{"switch": "TURN|SESSION|NO"}'
)


def _classify(llm: Any, text: str) -> str:
    try:
        res = llm.complete_structured(
            instructions=_CLASSIFY_INSTRUCTIONS,
            input=[{"type": "text", "text": text[:2000]}],
            json_mode=True, max_tokens=64, temperature=0.0, timeout=15,
            purpose="write-gate scope",
            # 分类走 auxiliary.approval 槽（需 plugins.entries.write-gate.llm.allow_task_override=true，
            # 缺失时宿主按信任拒绝→异常→保守 NO，不影响锁定安全）；与主模型解耦，省主会话尾延迟
            task="approval",
        )
        switch = (res.parsed or {}).get("switch", "") if hasattr(res, "parsed") else ""
        return switch if switch in ("TURN", "SESSION", "NO") else "NO"
    except Exception as err:
        logger.info("write-gate classifier unavailable (%s); treating as NO", err)
        return "NO"


def _on_post_tool_call(tool_name: str = "", result: Any = None, session_id: str = "",
                       turn_id: str = "", **_kw) -> None:
    try:
        if tool_name != "clarify" or not session_id or _exempt(session_id):
            return
        if not isinstance(result, str) or not result.strip().startswith("{"):
            return
        data = json.loads(result)
        if data.get("timed_out"):
            return
        responses = data.get("responses") or []
        # 只认闸门自己的确认卡：卡上选项须含「按此方案执行」。业务提问的 clarify
        # （选项是业务选项）一律忽略——否则用户对业务问题答一句"好/可以/做"，会被
        # 下面的语义分类判成 TURN，把整轮写入错误放行（2026-10-10 14:28 实测复现）。
        if not any(
            str(c).strip().startswith(APPROVE_LABEL)
            for r in responses
            for c in (r.get("choices_offered") or [])
        ):
            return
        answers = []
        for r in responses:
            ur = r.get("user_response", "")
            answers.append("；".join(ur) if isinstance(ur, list) else str(ur))
        joined = "\n".join(a for a in answers if a.strip()).strip()
        if not joined:
            return
        # ① 机械匹配：答案须与「按此方案执行」精确一致，或与卡上某个以该标记开头的选项
        # 精确一致（点选项＝选项原文回填）。v1.1.3 收紧：此前对 user_response 用
        # startswith，用户在自定义框里"引用"选项发问（"按此方案执行是什么意思？"）也会被
        # 机械放行整轮；卡身份识别（上面那段）仍用 startswith——闸门卡选项常带括号后缀。
        approve_answers = {APPROVE_LABEL} | {
            str(c).strip()
            for r in responses
            for c in (r.get("choices_offered") or [])
            if str(c).strip().startswith(APPROVE_LABEL)
        }
        with _LOCK:
            if any(a.strip() in approve_answers for a in answers if a.strip()):
                _unlock[session_id] = ("turn", turn_id)      # ① 机械匹配：本轮放行
                logger.info("write-gate: session %s unlocked TURN %s (mechanical)", session_id, turn_id)
                return
        # ② 全部回答恰为「取消」→ 机械判 NO 短路（零 LLM 调用——用户点拒绝不该花钱）
        non_empty = [a.strip() for a in answers if a.strip()]
        if non_empty and all(a == "取消" for a in non_empty):
            logger.info("write-gate: session %s answered CANCEL (mechanical, no classify)", session_id)
            return
        # ③ 自定义补充 → 语义分类（NO/LOCK 维持锁定）
        switch = _classify(_LLM, joined)
        if switch in ("TURN", "SESSION"):
            with _LOCK:
                _unlock[session_id] = (switch.lower(), turn_id)
            logger.info("write-gate: session %s unlocked %s (semantic)", session_id, switch)
    except Exception as err:
        logger.warning("write-gate post_tool_call error (ignored): %s", err)


# 收回通道已删（用户拍板：免问后反悔=重启/新会话，解锁态纯内存，新会话天然锁定）。


def _on_session_end(session_id: str = "", **_kw) -> None:
    """注意：桌面路径此钩子每条消息结束都触发（turn_finalizer），不是会话终止——
    绝不可清空 _unlock，否则 SESSION 级放行活不过一条消息。仅清来源缓存；
    新会话有新 session_id，天然从零锁定。"""
    with _LOCK:
        _source_cache.pop(session_id, None)
        _redirected.pop(session_id, None)     # 转派状态按消息结束清（turn 变化亦自动失效）
        _cwd_cache.pop(session_id, None)
        _changed_acc.pop(session_id, None)    # 本轮累计值同样不跨消息保留


_LLM: Any = None
_CTX: Any = None


def register(ctx) -> None:
    global _LLM, _CTX
    _LLM = ctx.llm
    _CTX = ctx
    try:
        logger.info("write-gate %s loaded from %s (delegate_after_approval=%s, delegate_min_lines=%s)",
                    _plugin_version(), os.path.dirname(os.path.abspath(__file__)),
                    _delegate_after_approval(), _delegate_min_lines())
    except Exception as err:                        # 日志失败不能拖垮装载
        logger.warning("write-gate startup log failed: %s", err)
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
    ctx.register_hook("post_tool_call", _on_post_tool_call)
    ctx.register_hook("on_session_end", _on_session_end)
