# -*- coding: utf-8 -*-
import os, threading
import streamlit as st
import streamlit.components.v1 as components
import json
import words as W
import copy_text as C
from engine import Hub, GameError

ERR = {
    "no_room": "الأوضة دي مش موجودة أو خلصت. اتأكد من الكود.",
    "locked": "اللعب بدأ والأوضة اتقفلت.",
    "name": "اكتب اسمك الأول.", "gender": "اختار واد ولا بت.",
    "dup_name": "في حد بنفس الاسم ده. غيّره حبة.", "full": "الأوضة اتملت.",
    "host_only": "ده للمضيف بس.", "phase": "مش وقت الحركة دي.",
    "min_players": "لازم لاعبين اتنين على الأقل.", "len": "مدة مش مظبوطة.",
    "not_in_round": "الجولة خلصت.", "no_target": "مفيش حد تتصيده دلوقتي.",
    "unknown_player": "الأوضة دي مش بتاعتك. ادخل تاني بالكود.", "no_code": "جرّب تاني بعد شوية.", "slow_down": "محاولات كتير غلط. استنى شوية وجرّب تاني.",
}

st.set_page_config(page_title="ماتقولهاش", layout="centered", initial_sidebar_state="collapsed")
st.markdown("""<style>
header,footer,#MainMenu{display:none!important}
.block-container{padding:0!important;max-width:440px!important}
iframe{height:100dvh!important;width:100%!important;border:0!important}
html,body,.stApp{background:#0A0F2E}
</style>""", unsafe_allow_html=True)

def _load_private():
    try:
        d = json.loads(st.secrets["game_text"])
    except Exception:
        return False
    W.BANK = sorted(set(d["bank"]))
    C.VICTIM_M = [(h, l) for h in d["heads_m"] for l in d["lines_m"]]
    C.VICTIM_F = [(h, l) for h in d["heads_f"] for l in d["lines_f"]]
    C.BANNER = d["banner"]; C.CONGRATS = d["congrats"]; C.ZERO_HIT = d["zero_hit"]; C.LAST_ROUND = d["last_round"]
    return True

@st.cache_resource
def shared():
    _load_private()
    return {"hub": Hub(), "lock": threading.Lock()}

def _clean(b):
    out = {}
    if not isinstance(b, dict):
        return out
    for k in ("room", "pid", "name", "gender", "avatar"):
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
    S = shared(); path = req["path"]; b = _clean(req.get("body"))
    if path not in ("/api/state", "/api/create", "/api/join", "/api/start", "/api/next", "/api/claim", "/api/newleague", "/api/refill"):
        return {"ok": False, "error": "bad", "msg": "حصلت مشكلة."}
    try:
        with S["lock"]:
            if path == "/api/state":
                return {"ok": True, "state": S["hub"].get(b.get("room"), who).view(b.get("pid"))}
            if path == "/api/create":
                r = S["hub"].create(); pid = r.add_player(b.get("name"), b.get("gender"), b.get("avatar"))
                return {"ok": True, "room": r.code, "pid": pid}
            r = S["hub"].get(b.get("room"), who)
            if path == "/api/join":
                pid = r.add_player(b.get("name"), b.get("gender"), b.get("avatar")); return {"ok": True, "room": r.code, "pid": pid}
            pid = b.get("pid")
            if pid not in r.players: raise GameError("unknown_player")
            {"/api/start": lambda: r.start_league(pid, b.get("minutes")), "/api/next": lambda: r.next_round(pid),
             "/api/claim": lambda: r.claim(pid), "/api/newleague": lambda: r.new_league(pid),
             "/api/refill": lambda: r.refill_bank(pid)}[path]()
            return {"ok": True}
    except GameError as e:
        return {"ok": False, "error": str(e), "msg": ERR.get(str(e), "حصلت مشكلة.")}

comp = components.declare_component("mq", path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "comp"))
from streamlit.runtime.scriptrunner import get_script_run_ctx
_ctx = get_script_run_ctx()
who = _ctx.session_id if _ctx else "-"
resp = st.session_state.get("resp")
val = comp(resp=resp, key="mq", default=None)
if val and val.get("id") != st.session_state.get("last_id"):
    st.session_state["last_id"] = val["id"]
    st.session_state["resp"] = {"id": val["id"], "json": handle(val, who)}
    st.rerun()
