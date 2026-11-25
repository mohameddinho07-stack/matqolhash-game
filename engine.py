# -*- coding: utf-8 -*-
"""ماتقولهاش game engine: rooms, rounds, shared missions, scoring. Pure logic, no I/O."""
import random, time, string, uuid
import words as W
import copy_text as C

MIN_PLAYERS = 2
MAX_PLAYERS = 20          # design target, not load-tested
ROUNDS_PER_LEAGUE = 3
LEN_OPTIONS = (4, 5, 7)   # minutes
DEFAULT_LEN = 5
AVATARS = ["fahlawy", "osta", "tuktuk", "captain", "haag", "foul",
           "baladi", "hijabi", "dalouaa", "dahiha", "hagga", "kaptna"]
ROOM_TTL = 6 * 3600


_DIG = {ord(a): str(i) for i, a in enumerate("٠١٢٣٤٥٦٧٨٩")}
_DIG.update({ord(a): str(i) for i, a in enumerate("۰۱۲۳۴۵۶۷۸۹")})

def norm_code(code):
    c = str(code or "").translate(_DIG).upper()
    return "".join(ch for ch in c if ch.isascii() and ch.isalnum())


class GameError(Exception):
    pass


class Room:
    def __init__(self, code, now=None):
        self.code = code
        self.salt = uuid.uuid4().hex
        self.created = now or time.time()
        self.touched = self.created
        self.players = {}           # pid -> dict
        self.order = []             # pids in join order
        self.host = None
        self.phase = "lobby"        # lobby | round | between | league_over | bank_over
        self.round_no = 0
        self.round_len = DEFAULT_LEN
        self.bank = list(W.BANK); random.shuffle(self.bank)
        self.used = []              # words dealt in this gathering (never reused unless host refills)
        self.league_no = 1
        self.scores = {}            # pid -> {"hit":n,"survive":n}
        self.history = []           # summaries of finished rounds in the current league
        self.nid = 0
        self.notes = {}             # pid -> list of notes
        self.round = None
        self.last_summary = None
        self.refilled = 0
        self.gone = {}              # pid -> player dict, for players who left (history stays readable)
        self.closed = False

    # ---------------- players
    def add_player(self, name, gender, avatar):
        if getattr(self, "closed", False):
            raise GameError("closed")
        if self.phase != "lobby":
            raise GameError("locked")
        name = (name or "").strip()[:14]
        if not name:
            raise GameError("name")
        if gender not in ("m", "f"):
            raise GameError("gender")
        if avatar not in AVATARS:
            avatar = AVATARS[len(self.order) % len(AVATARS)]
        if len(self.order) >= MAX_PLAYERS:
            raise GameError("full")
        if any(p["name"] == name for p in self.players.values()):
            raise GameError("dup_name")
        pid = uuid.uuid4().hex[:12]
        self.players[pid] = {"name": name, "gender": gender, "avatar": avatar}
        self.order.append(pid)
        self.scores[pid] = {"hit": 0, "survive": 0}
        self.notes[pid] = []
        if not self.host:
            self.host = pid
        self.touched = time.time()
        return pid

    def _note(self, pid, kind, **kw):
        self.nid += 1
        d = {"id": self.nid, "kind": kind}
        d.update(kw)
        self.notes[pid].append(d)

    # ---------------- flow
    def start_league(self, by, minutes=None):
        if by != self.host:
            raise GameError("host_only")
        if self.phase not in ("lobby", "league_over"):
            raise GameError("phase")
        if len(self.order) < MIN_PLAYERS:
            raise GameError("min_players")
        if minutes is not None:
            if minutes not in LEN_OPTIONS:
                raise GameError("len")
            self.round_len = minutes
        self.round_no = 0
        self.history = []
        self.scores = {p: {"hit": 0, "survive": 0} for p in self.order}
        self._begin_round()

    def next_round(self, by):
        if by != self.host:
            raise GameError("host_only")
        if self.phase != "between":
            raise GameError("phase")
        if len(self.order) < MIN_PLAYERS:
            raise GameError("min_players")
        self._begin_round()

    def _pl(self, p):
        return self.players.get(p) or self.gone.get(p) or {"name": "؟", "avatar": AVATARS[0], "gender": "m"}

    def leave(self, pid):
        """A player leaves for real: removed from the roster, targets reassigned, host handed over."""
        if pid not in self.players or pid not in self.order:
            raise GameError("unknown_player")
        r = self.round
        self.gone[pid] = self.players.pop(pid)
        self.order.remove(pid)
        if self.host == pid:
            self.host = self.order[0] if self.order else None
        if self.phase == "round" and r and not r["ended"]:
            r["targets"].pop(pid, None)
            for s in self.order:
                t = r["targets"].get(s)
                if t == pid or t is None or t in r["caught"]:
                    r["targets"][s] = self._pick_target(s, avoid=pid)
            if len(self.order) < MIN_PLAYERS:
                self._end_round(time.time())
            else:
                self.tick(time.time())
        self.touched = time.time()
        return len(self.order)

    def close(self, by):
        if by != self.host:
            raise GameError("host_only")
        self.closed = True
        self.touched = time.time()

    def refill_bank(self, by):
        """Explicit host action after exhaustion: words come back (and may repeat)."""
        if by != self.host:
            raise GameError("host_only")
        if self.phase != "bank_over":
            raise GameError("phase")
        self.bank = list(W.BANK); random.shuffle(self.bank)
        self.refilled += 1
        self.phase = "between" if self.round_no else "lobby"
        if self.phase == "between" and self.round_no >= ROUNDS_PER_LEAGUE:
            self.phase = "league_over"

    def _begin_round(self):
        n = len(self.order)
        if len(self.bank) < n:
            self.phase = "bank_over"
            return
        words = {}
        for pid in self.order:
            w = self.bank.pop()
            self.used.append(w)
            words[pid] = w
        self.round_no += 1
        now = time.time()
        self.round = {
            "start": now, "end": now + self.round_len * 60, "words": words,
            "caught": {}, "targets": {}, "hits": [], "first_hit_sent": False,
            "survivors": None, "ended": False,
        }
        for pid in self.order:
            self.round["targets"][pid] = self._pick_target(pid)
        self.phase = "round"
        self.touched = now

    def _uncaught(self):
        return [p for p in self.order if p not in self.round["caught"]]

    def _pick_target(self, pid, avoid=None):
        pool = [p for p in self._uncaught() if p != pid]
        if avoid:
            alt = [p for p in pool if p != avoid]
            pool = alt or pool
        return random.choice(pool) if pool else None

    # ---------------- gameplay
    def tick(self, now=None):
        now = now or time.time()
        if self.phase == "round" and not self.round["ended"]:
            if now >= self.round["end"] or not self._uncaught():
                self._end_round(now)

    def claim(self, pid, now=None):
        now = now or time.time()
        self.tick(now)
        if self.phase != "round":
            raise GameError("not_in_round")
        r = self.round
        v = r["targets"].get(pid)
        if v is None or v in r["caught"]:
            raise GameError("no_target")
        steerers = [s for s in self.order if r["targets"].get(s) == v]
        r["caught"][v] = now - r["start"]
        for s in steerers:
            self.scores[s]["hit"] += 1
        vp = self.players[v]
        head, line = random.choice(C.VICTIM_M if vp["gender"] == "m" else C.VICTIM_F)
        word = r["words"][v]
        r["hits"].append({"t": now - r["start"], "victim": v, "steerers": steerers, "word": word, "claimer": pid})
        self._note(v, "caught", head=head, line=line.format(w=word), word=word)
        for s in steerers:
            self._note(s, "congrats", text=random.choice(C.CONGRATS_F if vp["gender"] == "f" else C.CONGRATS).format(v=vp["name"]))
        involved = set(steerers) | {v}
        if not r["first_hit_sent"]:
            r["first_hit_sent"] = True
            others = [p for p in self.order if p not in involved]
            if others:
                text = random.choice(C.BANNER)
                for p in others:
                    self._note(p, "banner", text=text)
        # retarget every steerer assigned to the fallen victim, plus anyone pointing at a caught player
        for s in self.order:
            t = r["targets"].get(s)
            if t is not None and t in r["caught"]:
                r["targets"][s] = self._pick_target(s, avoid=t)
        self.touched = now
        self.tick(now)
        return v

    def _end_round(self, now):
        r = self.round
        r["ended"] = True
        surv = self._uncaught()
        r["survivors"] = list(surv)
        for p in surv:
            self.scores[p]["survive"] += 1
        zero = not r["hits"]
        summary = {
            "round": self.round_no, "zero": zero,
            "zero_text": random.choice(C.ZERO_HIT) if zero else None,
            "hits": [dict(h) for h in r["hits"]],
            "survivors": list(surv),
            "words": dict(r["words"]),
        }
        self.history.append(summary)
        self.last_summary = summary
        self.phase = "league_over" if self.round_no >= ROUNDS_PER_LEAGUE else "between"
        if self.phase == "league_over":
            self.league_no += 0
        self.touched = now

    def new_league(self, by):
        if by != self.host or self.phase != "league_over":
            raise GameError("phase")
        self.league_no += 1
        self.start_league(by)

    # ---------------- views (personalised: never leaks other players' words or targets)
    def total(self, pid):
        s = self.scores[pid]
        return s["hit"] + s["survive"]

    def standings(self):
        rows = [{"pid": p, "name": self.players[p]["name"], "avatar": self.players[p]["avatar"],
                 "hit": self.scores[p]["hit"], "survive": self.scores[p]["survive"], "total": self.total(p)}
                for p in self.order]
        rows.sort(key=lambda x: (-x["total"], -x["hit"], x["name"]))
        rank = 0; prev = None
        for i, r_ in enumerate(rows):
            key = r_["total"]
            if key != prev:
                rank = i + 1; prev = key
            r_["rank"] = rank
        return rows

    def view(self, pid, now=None):
        now = now or time.time()
        if getattr(self, "closed", False):
            raise GameError("closed")
        self.tick(now)
        if pid not in self.players:
            raise GameError("unknown_player")
        me = self.players[pid]
        v = {
            "code": self.code, "phase": self.phase, "now": now,
            "me": {"pid": pid, "name": me["name"], "gender": me["gender"], "avatar": me["avatar"], "host": pid == self.host},
            "players": [{"pid": p, "name": self.players[p]["name"], "avatar": self.players[p]["avatar"],
                         "gender": self.players[p]["gender"], "host": p == self.host} for p in self.order],
            "round_no": self.round_no, "rounds": ROUNDS_PER_LEAGUE, "round_len": self.round_len,
            "len_options": list(LEN_OPTIONS), "league_no": self.league_no, "min_players": MIN_PLAYERS,
            "notes": [n for n in self.notes[pid]][-6:],
            "standings": self.standings(),
            "words_left": len(self.bank), "refilled": self.refilled,
        }
        r = self.round
        if self.phase == "round" and r:
            t = r["targets"].get(pid)
            v["round"] = {
                "end": r["end"], "start": r["start"], "caught": pid in r["caught"],
                "target": None if t is None else {"pid": t, "name": self.players[t]["name"], "avatar": self.players[t]["avatar"],
                                                    "gender": self.players[t]["gender"], "word": r["words"][t]},
                "uncaught": len(self._uncaught()), "total": len(self.order),
                "my": dict(self.scores[pid]),
            }
        if self.phase in ("between", "league_over") and self.last_summary:
            s = self.last_summary
            nm = lambda p: self._pl(p)["name"]
            v["summary"] = {
                "round": s["round"], "zero": s["zero"], "zero_text": s["zero_text"],
                "hits": [{"t": h["t"], "victim": nm(h["victim"]), "victim_avatar": self._pl(h["victim"])["avatar"],
                          "steerers": [{"name": nm(x), "avatar": self._pl(x)["avatar"]} for x in h["steerers"]],
                          "word": h["word"]} for h in s["hits"]],
                "survivors": [nm(p) for p in s["survivors"]],
                "you_survived": pid in s["survivors"],
            }
        return self._public(v)

    def _public(self, o):
        # player ids are secrets (they authorize actions); the client only ever sees a salted public label
        if isinstance(o, dict):
            return {k: (self._pub(x) if k == "pid" and isinstance(x, str) else self._public(x)) for k, x in o.items()}
        if isinstance(o, list):
            return [self._public(x) for x in o]
        return o

    def _pub(self, pid):
        import hashlib
        return hashlib.sha256((self.salt + pid).encode()).hexdigest()[:8]


class Hub:
    def __init__(self):
        self.rooms = {}

    def _gc(self, now):
        for c in [c for c, r in self.rooms.items() if now - r.touched > ROOM_TTL]:
            del self.rooms[c]

    def create(self):
        now = time.time()
        self._gc(now)
        if len(self.rooms) >= 400:
            raise GameError("no_code")
        rng = random.SystemRandom()
        for _ in range(200):
            code = "".join(rng.choice("0123456789") for _ in range(6))
            if code not in self.rooms:
                self.rooms[code] = Room(code, now)
                return self.rooms[code]
        raise GameError("no_code")

    FAIL_SESSION = 8     # failed room lookups per session per minute
    FAIL_GLOBAL = 60    # failed room lookups across everyone per minute

    def _throttle(self, who):
        now = time.time()
        self._fails = [(t, w) for t, w in getattr(self, "_fails", []) if now - t < 60]
        if len(self._fails) >= self.FAIL_GLOBAL or sum(1 for _, w in self._fails if w == who) >= self.FAIL_SESSION:
            raise GameError("slow_down")

    def get(self, code, who="-"):
        r = self.rooms.get(norm_code(code))
        if not r:
            self._throttle(who)
            self._fails.append((time.time(), who))
            raise GameError("no_room")
        return r
