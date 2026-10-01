"""MysteryDetective — AI Mystery Detective game. Port 8014."""
import json
import os
import re
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

APP_TITLE = "MysteryDetective"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
MODEL = "openai/gpt-oss-120b"
PORT = int(os.getenv("PORT", "8014"))

app = FastAPI(title=APP_TITLE)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

# ---- process-global server memory only (never persisted, never sent to frontend) ----
_API_KEY: Optional[str] = os.getenv("GROQ_API_KEY") or None
_CASE: Optional[Dict[str, Any]] = None
_PROGRESS: Dict[str, Any] = {"found_evidence": [], "searched_locations": [], "questioned": []}
_ACCUSED: Optional[Dict[str, Any]] = None

# ---- persistent casefile: stops long-investigation drift (Holmes pattern, additive) ----
# Tracks verified events, alibi status, evidence found/unfound, and probe/accusation budgets.
MAX_PROBES = 12
MAX_ACCUSATIONS = 3
_CASEFILE: Optional[Dict[str, Any]] = None


def default_casefile(case: Dict[str, Any]) -> Dict[str, Any]:
    ev = [{"id": str(e.get("id", "")), "title": str(e.get("title", "")),
           "found": False} for e in case.get("evidence", [])]
    alibis = {str(s.get("name", "")): "unverified" for s in case.get("suspects", [])}
    return {"timeline": [], "alibis": alibis, "evidence": ev,
            "probes_used": 0, "probes_left": MAX_PROBES,
            "accusations_left": MAX_ACCUSATIONS, "accusations_used": []}


def get_casefile() -> Dict[str, Any]:
    """Lazily init (backward-compatible with old seeds/tests that only set _CASE)."""
    global _CASEFILE
    if _CASEFILE is None and _CASE is not None:
        _CASEFILE = default_casefile(_CASE)
    if _CASEFILE is None:
        _CASEFILE = {"timeline": [], "alibis": {}, "evidence": [],
                     "probes_used": 0, "probes_left": MAX_PROBES,
                     "accusations_left": MAX_ACCUSATIONS, "accusations_used": []}
    return _CASEFILE


def sync_casefile_evidence() -> None:
    cf = get_casefile()
    found = set(_PROGRESS.get("found_evidence", []))
    for e in cf.get("evidence", []):
        e["found"] = str(e.get("id", "")).upper() in {str(x).upper() for x in found}


def casefile_payload() -> Dict[str, Any]:
    cf = get_casefile()
    sync_casefile_evidence()
    return {"timeline": list(cf.get("timeline", []))[-20:],
            "alibis": dict(cf.get("alibis", {})),
            "evidence": [dict(e) for e in cf.get("evidence", [])],
            "probes_used": cf.get("probes_used", 0),
            "probes_left": max(0, MAX_PROBES - int(cf.get("probes_used", 0))),
            "accusations_left": cf.get("accusations_left", MAX_ACCUSATIONS),
            "accusations_used": list(cf.get("accusations_used", [])),
            "max_probes": MAX_PROBES, "max_accusations": MAX_ACCUSATIONS}


def note_verified_event(text: str) -> None:
    cf = get_casefile()
    t = str(text or "").strip()[:160]
    if not t:
        return
    cf.setdefault("timeline", []).append({"n": len(cf["timeline"]) + 1, "event": t})
    cf["timeline"] = cf["timeline"][-20:]  # cap size


def consume_probe() -> Optional[Dict[str, Any]]:
    """Returns 400-payload dict if budget exhausted, else None (and consumes one)."""
    cf = get_casefile()
    if int(cf.get("probes_used", 0)) >= MAX_PROBES:
        return {"ok": False, "error": f"No probes left ({MAX_PROBES} used). Review the evidence board and accuse or reveal.",
                "casefile": casefile_payload(), "progress": progress_payload(_CASE)}
    cf["probes_used"] = int(cf.get("probes_used", 0)) + 1
    cf["probes_left"] = max(0, MAX_PROBES - cf["probes_used"])
    return None

VALID_DIFFICULTIES = ("Cozy", "Classic", "Noir")


# ---------- models ----------
class KeyIn(BaseModel):
    key: str = Field(min_length=5, max_length=300)


class NewCaseIn(BaseModel):
    difficulty: str = "Classic"


class InterrogateIn(BaseModel):
    suspect: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=1000)


class InspectIn(BaseModel):
    evidence_id: str = Field(min_length=1, max_length=50)


class SearchIn(BaseModel):
    location: str = Field(min_length=1, max_length=100)


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


class AccuseIn(BaseModel):
    suspect: str = Field(min_length=1, max_length=100)
    reasoning: str = Field(min_length=1, max_length=2000)


# ---------- helpers ----------
def get_key() -> Optional[str]:
    return _API_KEY


def groq_client():
    from openai import OpenAI

    key = get_key()
    if not key:
        raise RuntimeError("no_api_key")
    return OpenAI(api_key=key, base_url=GROQ_BASE_URL)


def map_groq_error(exc: Exception) -> str:
    msg = str(exc).lower()
    if "401" in msg or "invalid api key" in msg or "unauthorized" in msg:
        return "Invalid API key. Open Settings and paste a valid Groq key."
    if "429" in msg or "rate limit" in msg:
        return "Groq rate limit hit. Wait a minute and try again."
    if "timeout" in msg or "connection" in msg or "network" in msg:
        return "Network error reaching Groq. Check your connection and retry."
    if "no_api_key" in msg:
        return "No API key set. Open Settings and add your Groq key."
    return f"Groq error: {str(exc)[:300]}"


def redact_text(text: str, culprit: str) -> str:
    """Consistency/no-leak guard: strip culprit's name from non-reveal outputs."""
    if not text or not culprit:
        return text
    parts = [p for p in re.split(r"\s+", culprit.strip()) if p]
    out = text
    for p in parts:
        if len(p) >= 3:
            out = re.sub(re.escape(p), "[redacted]", out, flags=re.IGNORECASE)
    # also redact explicit "culprit is X" phrasing leftovers
    return out


def create_fallback_case(difficulty: str = "Classic") -> Dict[str, Any]:
    tone = {"Cozy": "a snowy village inn", "Classic": "a foggy London townhouse", "Noir": "a rain-soaked downtown bar"}.get(difficulty, "a foggy London townhouse")
    return {
        "title": f"Theft at {tone.title()}",
        "intro": f"A priceless pocket watch vanished during a stormy night at {tone}. Three guests remain. Find the truth.",
        "culprit": "Elena Marsh",
        "solution_summary": "Elena Marsh took the watch to pay a debt, staging a locked-door trick with fishing line through the keyhole.",
        "suspects": [
            {"name": "Elena Marsh", "motive": "Owens gambling debts, seen near the study.", "secret": "Owes money; stole watch with fishing line trick."},
            {"name": "Tom Beck", "motive": "Argued with the victim over wages.", "secret": "Was in the cellar fetching wine at the time."},
            {"name": "Priya Nair", "motive": "Writing an expose on the victim.", "secret": "Was copying letters in the library; heard a creak upstairs."},
        ],
        "locations": [
            {"name": "Study", "clues": ["A thin fishing line caught on the keyhole.", "Muddy footprint by the window, size small."]},
            {"name": "Library", "clues": ["A copied letter mentions debts.", "A chair still warm near the desk."]},
            {"name": "Cellar", "clues": ["Wine bottle with fresh fingerprints.", "A corkscrew left on the stairs."]},
        ],
        "evidence": [
            {"id": "E1", "title": "Fishing line", "detail": "Thin line snagged inside the study keyhole — classic locked-door trick.", "location": "Study"},
            {"id": "E2", "title": "Muddy footprint", "detail": "Small muddy print by the study window, pointing inward.", "location": "Study"},
            {"id": "E3", "title": "Debt letter", "detail": "A copied letter referencing urgent gambling debts.", "location": "Library"},
        ],
        "timeline": [
            {"time": "21:00", "event": "Storm knocks out the lights briefly."},
            {"time": "21:15", "event": "Argument heard between victim and a staff member."},
            {"time": "21:30", "event": "Watch last seen on the study desk."},
            {"time": "22:00", "event": "Watch found missing; doors locked from inside."},
        ],
        "difficulty": difficulty,
    }


CASE_SCHEMA_HINT = """Return ONLY valid JSON with exactly these keys:
{"title": string, "intro": string (2-3 sentences), "culprit": string (exact suspect name),
"solution_summary": string (2-4 sentences, how + why),
"suspects": [{"name": string, "motive": string, "secret": string}] (exactly 3),
"locations": [{"name": string, "clues": [string, string]}] (exactly 3 locations, 2 clues each),
"evidence": [{"id": string like E1, "title": string, "detail": string, "location": string}] (exactly 4),
"timeline": [{"time": string, "event": string}] (4-5 entries)}.
Rules: clues and evidence details describe physical facts but NEVER contain the culprit's name. Timeline never names the culprit."""


def build_case_prompt(difficulty: str) -> str:
    flavor = {
        "Cozy": "Cozy mystery: charming village, low violence, a theft or harmless disappearance, warm tone.",
        "Classic": "Classic whodunit: country-house style, fair-play clues, logical deduction.",
        "Noir": "Noir: rain, neon, moral ambiguity, hardboiled tone but still fair-play.",
    }.get(difficulty, "Classic whodunit.")
    return f"You write a solvable detective case. {flavor} Difficulty: {difficulty}.\n{CASE_SCHEMA_HINT}"


def parse_case_json(raw: str) -> Dict[str, Any]:
    raw = raw.strip()
    # defensive: strip code fences
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw).strip()
        raw = re.sub(r"```$", "", raw).strip()
    obj = json.loads(raw)
    # validate shape
    for k in ("title", "intro", "culprit", "solution_summary", "suspects", "locations", "evidence", "timeline"):
        if k not in obj:
            raise ValueError(f"missing key: {k}")
    if not isinstance(obj["suspects"], list) or len(obj["suspects"]) != 3:
        raise ValueError("suspects must be a list of 3")
    names = [s.get("name", "") for s in obj["suspects"]]
    if obj["culprit"] not in names:
        raise ValueError("culprit must match one suspect name")
    return obj


def generate_case(difficulty: str) -> Dict[str, Any]:
    """Full case generation upfront server-side. Retries once on parse fail."""
    if difficulty not in VALID_DIFFICULTIES:
        raise ValueError(f"Invalid difficulty. Choose {', '.join(VALID_DIFFICULTIES)}.")
    client = groq_client()
    last_err: Optional[Exception] = None
    for _attempt in range(2):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": "You are a mystery-case generator. Output valid JSON only."},
                    {"role": "user", "content": build_case_prompt(difficulty)},
                ],
                temperature=0.9,
                max_tokens=2000,
            )
            raw = resp.choices[0].message.content or ""
            case = parse_case_json(raw)
            case["difficulty"] = difficulty
            return case
        except Exception as e:  # noqa: BLE001 — retry once then map
            last_err = e
    raise RuntimeError(f"parse_fail: {last_err}")


def redact_case(case: Dict[str, Any]) -> Dict[str, Any]:
    """Public subset — NEVER includes culprit/solution/secret/detail."""
    return {
        "title": case["title"],
        "intro": case["intro"],
        "difficulty": case.get("difficulty", "Classic"),
        "suspects": [{"name": s["name"], "motive": s.get("motive", "")} for s in case["suspects"]],
        "locations": [{"name": loc["name"]} for loc in case["locations"]],
        "evidence": [{"id": e["id"], "title": e["title"], "location": e.get("location", "")} for e in case["evidence"]],
        "timeline": case["timeline"],
        "brief": f"{len(case['suspects'])} suspects, {len(case['evidence'])} pieces of evidence, {len(case['locations'])} locations.",
    }


def suspect_names(case: Dict[str, Any]) -> List[str]:
    return [s["name"] for s in case.get("suspects", [])]


def find_suspect(case: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    nl = name.strip().lower()
    for s in case.get("suspects", []):
        if s["name"].strip().lower() == nl:
            return s
    return None


def progress_payload(case: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    total_ev = len(case["evidence"]) if case else 0
    total_loc = len(case["locations"]) if case else 0
    cf = get_casefile() if case else None
    base = {
        "clues_found": len(_PROGRESS["found_evidence"]) + len(_PROGRESS["searched_locations"]),
        "clues_total": total_ev + total_loc,
        "evidence_found": sorted(_PROGRESS["found_evidence"]),
        "searched": sorted(_PROGRESS["searched_locations"]),
        "questioned": sorted(_PROGRESS["questioned"]),
        "suspects_questioned": len(_PROGRESS["questioned"]),
    }
    # additive counters — old clients ignore them, new board uses them
    if cf is not None:
        base.update({"probes_used": cf.get("probes_used", 0),
                     "probes_left": max(0, MAX_PROBES - int(cf.get("probes_used", 0))),
                     "accusations_left": cf.get("accusations_left", MAX_ACCUSATIONS),
                     "max_probes": MAX_PROBES, "max_accusations": MAX_ACCUSATIONS})
    return base


def require_case() -> Dict[str, Any]:
    if not _CASE:
        raise RuntimeError("no_case")
    return _CASE


# ---------- routes ----------
@app.get("/api/status")
def api_status():
    return {"has_key": bool(_API_KEY), "has_case": bool(_CASE), "model": MODEL}


@app.post("/api/key")
def api_set_key(body: KeyIn):
    global _API_KEY
    key = body.key.strip()
    # live-verify via models.list
    try:
        from openai import OpenAI

        c = OpenAI(api_key=key, base_url=GROQ_BASE_URL)
        c.models.list()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": map_groq_error(e)}
    _API_KEY = key
    return {"ok": True}


@app.delete("/api/key")
def api_delete_key():
    global _API_KEY
    _API_KEY = None
    return {"ok": True}


@app.post("/api/new-case")
def api_new_case(body: NewCaseIn):
    global _CASE, _PROGRESS, _ACCUSED, _CASEFILE
    diff = body.difficulty.strip().capitalize()
    if diff not in VALID_DIFFICULTIES:
        return {"ok": False, "error": f"Invalid difficulty. Choose {', '.join(VALID_DIFFICULTIES)}."}
    if not get_key():
        # offline fallback so the game is still playable without a key
        _CASE = create_fallback_case(diff)
        _PROGRESS = {"found_evidence": [], "searched_locations": [], "questioned": []}
        _ACCUSED = None
        _CASEFILE = default_casefile(_CASE)
        out = redact_case(_CASE)
        out.update({"ok": True, "offline": True, "progress": progress_payload(_CASE),
                    "casefile": casefile_payload()})
        return out
    try:
        _CASE = generate_case(diff)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": map_groq_error(e)}
    _PROGRESS = {"found_evidence": [], "searched_locations": [], "questioned": []}
    _ACCUSED = None
    _CASEFILE = default_casefile(_CASE)
    out = redact_case(_CASE)
    out.update({"ok": True, "progress": progress_payload(_CASE), "casefile": casefile_payload()})
    return out


@app.post("/api/interrogate")
def api_interrogate(body: InterrogateIn):
    try:
        case = require_case()
    except RuntimeError:
        return {"ok": False, "error": "Start a new case first."}
    sus = find_suspect(case, body.suspect)
    if not sus:
        return {"ok": False, "error": f"Unknown suspect. Choose: {', '.join(suspect_names(case))}."}
    q = body.question.strip()
    if not q:
        return {"ok": False, "error": "Ask a question first."}
    blocked = consume_probe()
    if blocked:
        return JSONResponse(blocked, status_code=400)
    cf = get_casefile()
    if sus["name"] not in _PROGRESS["questioned"]:
        _PROGRESS["questioned"].append(sus["name"])
    cf["alibis"][sus["name"]] = "questioned"
    note_verified_event(f"Questioned {sus['name']}: {q[:80]}")
    # offline path
    if not get_key():
        others = [s for s in case["suspects"] if s["name"] != sus["name"]]
        txt = (
            f"[{sus['name']}, offline reply] You ask: '{q}'. "
            f"I was minding my own business — ask about {others[0]['name']} or check the evidence board. "
            f"My motive? {sus.get('motive','')} But I did nothing."
        )
        return {"ok": True, "suspect": sus["name"], "answer": redact_text(txt, case["culprit"]),
                "progress": progress_payload(case), "casefile": casefile_payload()}
    try:
        client = groq_client()
        sys = (
            f"You are {sus['name']} in a murder-mystery game. Case file: {json.dumps(case)}. "
            f"Your motive: {sus.get('motive','')}. Your secret: {sus.get('secret','')}. "
            "Answer IN CHARACTER, stay consistent with the case file. "
            "NEVER reveal who the culprit is, never say the culprit's name, never confess for anyone. "
            "If you are the culprit, deflect calmly and never confess. Keep answers under 120 words."
        )
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "system", "content": sys}, {"role": "user", "content": q}],
            temperature=0.7, max_tokens=400,
        )
        ans = resp.choices[0].message.content or ""
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": map_groq_error(e)}
    return {"ok": True, "suspect": sus["name"], "answer": redact_text(ans, case["culprit"]),
            "progress": progress_payload(case), "casefile": casefile_payload()}


@app.post("/api/inspect")
def api_inspect(body: InspectIn):
    try:
        case = require_case()
    except RuntimeError:
        return {"ok": False, "error": "Start a new case first."}
    eid = body.evidence_id.strip().upper()
    ev = next((e for e in case.get("evidence", []) if str(e.get("id", "")).upper() == eid), None)
    if not ev:
        return {"ok": False, "error": f"Unknown evidence id. Available: {', '.join(e['id'] for e in case['evidence'])}."}
    blocked = consume_probe()
    if blocked:
        return JSONResponse(blocked, status_code=400)
    if eid not in _PROGRESS["found_evidence"]:
        _PROGRESS["found_evidence"].append(eid)
    note_verified_event(f"Inspected {ev['id']} ({ev['title']}) @ {ev.get('location','')}")
    return {
        "ok": True, "evidence": {"id": ev["id"], "title": ev["title"], "detail": redact_text(ev.get("detail", ""), case["culprit"]), "location": ev.get("location", "")},
        "progress": progress_payload(case), "casefile": casefile_payload(),
    }


@app.post("/api/search")
def api_search(body: SearchIn):
    try:
        case = require_case()
    except RuntimeError:
        return {"ok": False, "error": "Start a new case first."}
    loc = next((l for l in case.get("locations", []) if l["name"].strip().lower() == body.location.strip().lower()), None)
    if not loc:
        return {"ok": False, "error": f"Unknown location. Available: {', '.join(l['name'] for l in case['locations'])}."}
    blocked = consume_probe()
    if blocked:
        return JSONResponse(blocked, status_code=400)
    if loc["name"] not in _PROGRESS["searched_locations"]:
        _PROGRESS["searched_locations"].append(loc["name"])
    note_verified_event(f"Searched {loc['name']}")
    clues = [redact_text(c, case["culprit"]) for c in loc.get("clues", [])]
    return {"ok": True, "location": loc["name"], "clues": clues,
            "progress": progress_payload(case), "casefile": casefile_payload()}


@app.post("/api/ask")
def api_ask(body: AskIn):
    try:
        case = require_case()
    except RuntimeError:
        return {"ok": False, "error": "Start a new case first."}
    q = body.question.strip()
    if not q:
        return {"ok": False, "error": "Ask something first."}
    if not get_key():
        return {"ok": True, "hint": "Cross-check alibis against the timeline, then inspect each evidence item in the location it was found."}
    # hint without spoiling: only send redacted brief, never culprit/solution
    try:
        client = groq_client()
        brief = json.dumps(redact_case(case))
        sys = (
            "You are a hint assistant for a detective game. NEVER reveal the culprit's name, never state the solution, "
            "never quote secrets. Only suggest investigative next steps (who to question, what to inspect) based on the brief. "
            f"Case brief: {brief}. Keep hints under 80 words."
        )
        resp = client.chat.completions.create(
            model=MODEL, messages=[{"role": "system", "content": sys}, {"role": "user", "content": q}],
            temperature=0.5, max_tokens=250,
        )
        hint = resp.choices[0].message.content or ""
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": map_groq_error(e)}
    return {"ok": True, "hint": redact_text(hint, case["culprit"])}


@app.post("/api/accuse")
def api_accuse(body: AccuseIn):
    global _ACCUSED
    try:
        case = require_case()
    except RuntimeError:
        return {"ok": False, "error": "Start a new case first."}
    sus = find_suspect(case, body.suspect)
    if not sus:
        return {"ok": False, "error": f"Unknown suspect. Choose: {', '.join(suspect_names(case))}."}
    if not body.reasoning.strip():
        return {"ok": False, "error": "Give your reasoning first."}
    cf = get_casefile()
    if int(cf.get("accusations_left", MAX_ACCUSATIONS)) <= 0:
        return JSONResponse({"ok": False, "error": f"No accusations left ({MAX_ACCUSATIONS} used). Reveal the solution to close the file.",
                             "casefile": casefile_payload(), "progress": progress_payload(case)}, status_code=400)
    cf["accusations_left"] = int(cf.get("accusations_left", MAX_ACCUSATIONS)) - 1
    win = sus["name"].strip().lower() == case["culprit"].strip().lower()
    cf.setdefault("accusations_used", []).append({"suspect": sus["name"], "win": win})
    note_verified_event(f"Accused {sus['name']} — {'CORRECT' if win else 'wrong'}")
    _ACCUSED = {"suspect": sus["name"], "win": win}
    msg = "Correct! The evidence points to them." if win else "Wrong accusation — the real culprit walks free... for now. Review the clues or reveal the solution."
    return {"ok": True, "win": win, "suspect": sus["name"], "message": msg,
            "accusations_left": cf["accusations_left"],
            "progress": progress_payload(case), "casefile": casefile_payload()}


@app.post("/api/reveal")
def api_reveal():
    try:
        case = require_case()
    except RuntimeError:
        return {"ok": False, "error": "Start a new case first."}
    lines = [f"- {e['id']} ({e['title']} @ {e.get('location','')}): {e.get('detail','')}" for e in case.get("evidence", [])]
    explanation = "How the clues point to the culprit:\n" + "\n".join(lines)
    explanation += f"\n\nTimeline: " + "; ".join(f"{t['time']} — {t['event']}" for t in case.get("timeline", []))
    return {
        "ok": True, "title": case["title"], "culprit": case["culprit"],
        "solution_summary": case["solution_summary"], "explanation": explanation,
        "suspects": case["suspects"], "accused": _ACCUSED,
    }


@app.get("/api/state")
def api_state():
    if not _CASE:
        return {"ok": True, "has_case": False}
    out = redact_case(_CASE)
    out.update({"ok": True, "has_case": True, "progress": progress_payload(_CASE),
                "casefile": casefile_payload(), "accused": _ACCUSED})
    return out


# ---------- static ----------
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT)
