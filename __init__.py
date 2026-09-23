"""write-gate — 确认闸门（没按过按钮就不许写）。

插件的唯一职责：动工前给用户一个按钮。三级确认范围：
  · 单次回复（默认）：点「按此方案执行」→ 本轮 agent 运行内全部写入静默；
    用户下一条消息（新 turn_id）起自动重新锁定；
  · 单次会话：确认卡自定义框表达"这个会话都别问了" → 会话级放行，
    反悔方式 = 重启或新开会话（解锁态纯内存，新会话天然锁定）；
  · 所有会话：设置→插件 页拨 write-gate 开关。
不判定路径、不设时间窗、不维护白名单——范围与计划是模型和用户之间的事。

拦截 write_file / patch / memory / execute_code(代码含写模式)：
锁定状态下发起一律 block，指示模型「正文呈现方案 → 调 clarify 出确认卡」。
fail-open：本插件任何内部异常都放行（最坏退回无闸门状态，不卡死会话）。
豁免：非 desktop 来源会话（oneshot/cron/qqbot 等无确认卡 UI）、delegation 子会话
（clarify 被禁用，防死锁）、环境变量 WRITE_GATE=off。
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

APPROVE_LABEL = "按此方案执行"
_MANAGED = ("write_file", "patch", "memory", "execute_code")

_LOCK = threading.Lock()
# session_id -> (scope, turn_id)；scope ∈ {"turn","session"}
_unlock: Dict[str, Tuple[str, str]] = {}
_source_cache: Dict[str, tuple] = {}         # session_id -> (source, parent, ts)

# execute_code 写模式：命中任一即视为写操作。防糊涂不防执意（README 有言在先）。
_WRITE_PATTERNS = [
    re.compile(r"\bopen\s*\([^)]{0,200}?['\"][wax][+btu]*['\"]"),
    re.compile(r"\bshutil\.(copy\w*|move|rmtree|remove|unlink)\b"),
    re.compile(r"\bos\.(remove|unlink|rename|replace|makedirs?|rmdir|truncate)\b"),
    re.compile(r"\.write_text\s*\(|\.write_bytes\s*\(|\.touch\s*\(|\.mkdir\s*\(|\.unlink\s*\(|\.rename\s*\("),
    re.compile(r"\bsubprocess\.\w+\b[^#\n]*[>'>]{1,2}\s*\S"),
]


def _env_off() -> bool:
    return os.environ.get("WRITE_GATE", "").strip().lower() in {"off", "0", "no", "false"}


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


def _exempt(session_id: str) -> bool:
    """非交互/无卡会话豁免：oneshot、cron、qqbot、子代理、以及任何非 desktop 来源。"""
    if _env_off():
        return True
    if not session_id:
        return True  # 拿不到会话身份，不猜——放行（fail-open）
    source, parent = _session_meta(session_id)
    return source != "desktop" or bool(parent)


def _is_write(tool_name: str, args: Dict[str, Any]) -> bool:
    """该调用是否落在受管写操作上（execute_code 仅当代码含写模式）。"""
    if tool_name in ("write_file", "patch", "memory"):
        return True
    if tool_name == "execute_code":
        code = args.get("code") or ""
        return any(rx.search(code) for rx in _WRITE_PATTERNS)
    return False


_BLOCK_MSG = (
    "[write-gate] 该写操作未获用户确认，已被拦下（文件/记忆未发生任何变化）。\n"
    "请严格按以下流程处理：\n"
    "1) 在回复正文向用户呈现方案：本次要执行的全部写入目标（路径级）、目的与步骤；\n"
    f"2) 调用 clarify 请用户拍板，问题附选项：「{APPROVE_LABEL}」（放第一个）、「取消」；"
    "用户可在自定义框补充意见；\n"
    "3) 卡片中注明：批准后本轮回复内不再询问，用户下一条消息起恢复确认；\n"
    "4) 用户批准后，重试本调用即自动放行；用户提出修改意见时，按意见更新方案后重新出卡，"
    "不要自行猜测放行。\n"
    "禁止：改用 terminal/其他通道绕过闸门；未获 clarify 批准前反复重试同一调用。"
    "被拦后向用户呈现方案并等待，本身就是合法的回合交付。"
)


def _on_pre_tool_call(tool_name: str = "", args: Any = None, session_id: str = "",
                      turn_id: str = "", **_kw) -> Optional[Dict[str, str]]:
    try:
        if tool_name not in _MANAGED:
            return None
        if not isinstance(args, dict) or _exempt(session_id):
            return None
        if not _is_write(tool_name, args):
            return None
        with _LOCK:
            u = _unlock.get(session_id)
            if u and (u[0] == "session" or (u[0] == "turn" and u[1] and u[1] == turn_id)):
                return None
        return {"action": "block", "message": _BLOCK_MSG}
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
        answers = []
        for r in (data.get("responses") or []):
            ur = r.get("user_response", "")
            answers.append("；".join(ur) if isinstance(ur, list) else str(ur))
        joined = "\n".join(a for a in answers if a.strip()).strip()
        if not joined:
            return
        with _LOCK:
            if any(a.strip().startswith(APPROVE_LABEL) for a in answers if a.strip()):
                _unlock[session_id] = ("turn", turn_id)      # ① 机械匹配：本轮放行
                logger.info("write-gate: session %s unlocked TURN %s (mechanical)", session_id, turn_id)
                return
        # ② 自定义补充 → 语义分类（NO/LOCK 维持锁定）
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


_LLM: Any = None


def register(ctx) -> None:
    global _LLM
    _LLM = ctx.llm
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
    ctx.register_hook("post_tool_call", _on_post_tool_call)
    ctx.register_hook("on_session_end", _on_session_end)
