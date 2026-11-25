# -*- coding: utf-8 -*-
import os, threading
import streamlit as st
import streamlit.components.v1 as components
import json
import words as W
import copy_text as C
import importlib, engine as _eng
_mt = os.path.getmtime(_eng.__file__)
if getattr(_eng, "_MT", None) != _mt:
    # the host may keep an old engine module in memory after a code update; reload it, live rooms are re-pointed by _migrate
    importlib.reload(_eng)
    _eng._MT = _mt
from engine import Hub, GameError

ERR = {
    "no_room": "الأوضة دي مش موجودة أو خلصت. اتأكد من الكود.",
    "locked": "اللعب بدأ والأوضة اتقفلت.",
    "name": "اكتب اسمك الأول.", "gender": "اختار واد ولا بت.",
    "dup_name": "في حد بنفس الاسم ده. غيّره حبة.", "full": "الأوضة اتملت.",
    "host_only": "ده للمضيف بس.", "phase": "مش وقت الحركة دي.",
    "min_players": "لازم لاعبين اتنين على الأقل.", "len": "مدة مش مظبوطة.",
    "not_in_round": "الجولة خلصت.", "no_target": "مفيش حد تتصيده دلوقتي.", "stale_target": "", "no_undo": "مفيش حاجة تتلغي دلوقتي.",
    "unknown_player": "الأوضة دي مش بتاعتك. ادخل تاني بالكود.", "closed": "المضيف قفل الأوضة.", "pools": "اللعبة بتتجهز. جرّب تاني بعد دقيقة.", "no_code": "جرّب تاني بعد شوية.", "slow_down": "محاولات كتير غلط. استنى شوية وجرّب تاني.",
}

st.set_page_config(page_title="ماتقولهاش", layout="centered", initial_sidebar_state="collapsed")
st.markdown("""<style>
header,footer,#MainMenu{display:none!important}
.block-container{padding:0!important;max-width:440px!important}
iframe{height:100dvh!important;width:100%!important;border:0!important}
html,body,.stApp{background:#0A0F2E}
</style>""", unsafe_allow_html=True)

PRIV_ERR = {"e": ""}
def _load_private():
    try:
        d = json.loads(st.secrets["game_text"])
    except Exception as ex:
        PRIV_ERR["e"] = type(ex).__name__
        return False
    W.BANK = sorted(set(d["bank"]))
    C.VICTIM_M = [(h, l) for h in d["heads_m"] for l in d["lines_m"]]
    C.VICTIM_F = [(h, l) for h in d["heads_f"] for l in d["lines_f"]]
    C.BANNER = d["banner"]; C.CONGRATS = d["congrats"]; C.CONGRATS_F = d.get("congrats_f") or d["congrats"]; C.ZERO_HIT = d["zero_hit"]; C.LAST_ROUND = d["last_round"]
    C.PRIVATE = True; PRIV_ERR["e"] = ""
    return True

@st.cache_resource
def shared():
    _load_private()
    return {"hub": Hub(), "lock": threading.Lock()}

def _ensure_private():
    # Re-apply the private pools whenever they are not active (a cached first load can have failed or been reset).
    if not getattr(C, "PRIVATE", False):
        _load_private()

def _migrate(S):
    """Code updates keep live rooms: re-point existing room objects at the current Room class and fill new fields."""
    import engine as _E
    hub = S["hub"]
    if hub.__class__ is not _E.Hub:
        hub.__class__ = _E.Hub
    for _r in list(hub.rooms.values()):
        if _r.__class__ is not _E.Room:
            _r.__class__ = _E.Room
        if not hasattr(_r, "gone"):
            _r.gone = {}
        if not hasattr(_r, "closed"):
            _r.closed = False

def _clean(b):
    out = {}
    if not isinstance(b, dict):
        return out
    for k in ("room", "pid", "name", "gender", "avatar", "tgt"):
        v = b.get(k)
        out[k] = v[:40] if isinstance(v, str) else None
    m = b.get("minutes")
    out["minutes"] = m if type(m) is int else None
    if out["name"]:
        out["name"] = "".join(ch for ch in out["name"] if ch.isprintable() and ch not in "<>&\"'`").strip()
    return out

def handle(req, who="-"):
    try:
        return _handle(req, who)
    except Exception:
        return {"ok": False, "error": "bad", "msg": "حصلت مشكلة. جرّب تاني."}

def _handle(req, who="-"):
    if not isinstance(req, dict) or not isinstance(req.get("path"), str):
        return {"ok": False, "error": "bad", "msg": "حصلت مشكلة."}
    S = shared(); _ensure_private(); _migrate(S); path = req["path"]; b = _clean(req.get("body"))
    if not getattr(C, "PRIVATE", False) and path != "/api/health":
        return {"ok": False, "error": "pools", "msg": ERR["pools"]}
    if path not in ("/api/state", "/api/create", "/api/join", "/api/start", "/api/next", "/api/claim", "/api/newleague", "/api/refill", "/api/leave", "/api/close", "/api/undo", "/api/health"):
        return {"ok": False, "error": "bad", "msg": "حصلت مشكلة."}
    try:
        with S["lock"]:
            _st = S["hub"].__dict__.setdefault("stats", {})
            _st[path] = _st.get(path, 0) + 1
            if path == "/api/health":
                return {"ok": True, "pools": {"private": bool(getattr(C, "PRIVATE", False)), "bank": len(W.BANK), "victim_m": len(C.VICTIM_M), "victim_f": len(C.VICTIM_F), "err": PRIV_ERR["e"]}, "calls": dict(_st)}
            if path == "/api/state":
                return {"ok": True, "state": S["hub"].get(b.get("room"), who).view(b.get("pid"))}
            if path == "/api/create":
                r = S["hub"].create(); pid = r.add_player(b.get("name"), b.get("gender"), b.get("avatar"))
                return {"ok": True, "room": r.code, "pid": pid}
            r = S["hub"].get(b.get("room"), who)
            if path == "/api/join":
                pid = r.add_player(b.get("name"), b.get("gender"), b.get("avatar")); r._undo = None; return {"ok": True, "room": r.code, "pid": pid}
            pid = b.get("pid")
            if pid not in r.players: raise GameError("unknown_player")
            if path == "/api/leave":
                left = r.leave(pid); r._undo = None
                if not left:
                    S["hub"].rooms.pop(r.code, None)
                return {"ok": True}
            {"/api/start": lambda: r.start_league(pid, b.get("minutes")), "/api/next": lambda: r.next_round(pid),
             "/api/claim": lambda: r.claim(pid, expect=b.get("tgt")), "/api/undo": lambda: r.undo(pid), "/api/newleague": lambda: r.new_league(pid),
             "/api/refill": lambda: r.refill_bank(pid), "/api/close": lambda: r.close(pid)}[path]()
            if path not in ("/api/claim", "/api/undo"):
                r._undo = None
            out = {"ok": True}
            if path in ("/api/start", "/api/next", "/api/claim", "/api/undo", "/api/newleague", "/api/refill"):
                try: out["state"] = r.view(pid)
                except Exception: pass
            return out
    except GameError as e:
        return {"ok": False, "error": str(e), "msg": ERR.get(str(e), "حصلت مشكلة.")}

comp = components.declare_component("mq", path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "comp"))
from streamlit.runtime.scriptrunner import get_script_run_ctx
_ctx = get_script_run_ctx()
who = _ctx.session_id if _ctx else "-"
resp = st.session_state.get("resp")
val = st.session_state.get("mq")
if isinstance(val, dict) and val.get("id") and val.get("id") != st.session_state.get("last_id"):
    st.session_state["last_id"] = val["id"]
    resp = {"id": val["id"], "json": handle(val, who)}
    st.session_state["resp"] = resp
comp(resp=resp, key="mq", default=None)
