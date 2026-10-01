"""Casefile + probe/accusation limit tests (no network)."""
from fastapi.testclient import TestClient

import app as M

client = TestClient(M.app)


def _seed():
    M._CASE = M.create_fallback_case("Classic")
    M._PROGRESS = {"found_evidence": [], "searched_locations": [], "questioned": []}
    M._ACCUSED = None
    M._CASEFILE = M.default_casefile(M._CASE)
    return M._CASE


def test_casefile_init():
    case = _seed()
    cf = M.casefile_payload()
    assert cf["probes_used"] == 0 and cf["probes_left"] == M.MAX_PROBES
    assert cf["accusations_left"] == M.MAX_ACCUSATIONS
    assert len(cf["evidence"]) == len(case["evidence"])
    assert all(e["found"] is False for e in cf["evidence"])
    assert all(v == "unverified" for v in cf["alibis"].values())


def test_casefile_update_persist_offline():
    _seed()
    M._API_KEY = None  # offline branch, no Groq
    case = M._CASE
    eid = case["evidence"][0]["id"]
    r = client.post("/api/inspect", json={"evidence_id": eid})
    assert r.status_code == 200, r.text
    assert r.json()["casefile"]["probes_used"] == 1
    assert r.json()["casefile"]["evidence"][0]["found"] is True
    # timeline records verified event
    assert any(eid in t["event"] for t in r.json()["casefile"]["timeline"])
    # alibi update via interrogate
    sus = case["suspects"][0]["name"]
    r2 = client.post("/api/interrogate", json={"suspect": sus, "question": "Where were you?"})
    assert r2.status_code == 200
    assert r2.json()["casefile"]["alibis"][sus] == "questioned"
    assert r2.json()["casefile"]["probes_used"] == 2
    # /api/state persists it
    st = client.get("/api/state").json()
    assert st["casefile"]["probes_used"] == 2
    assert st["progress"]["probes_left"] == M.MAX_PROBES - 2


def test_probe_limit_enforced_400():
    _seed()
    M._API_KEY = None
    case = M._CASE
    loc = case["locations"][0]["name"]
    for _ in range(M.MAX_PROBES):
        r = client.post("/api/search", json={"location": loc})
        assert r.status_code == 200, r.text
    r = client.post("/api/search", json={"location": loc})
    assert r.status_code == 400
    assert r.json()["ok"] is False and "probe" in r.json()["error"].lower()


def test_accusation_limits_enforced_400():
    _seed()
    case = M._CASE
    other = [s for s in case["suspects"] if s["name"] != case["culprit"]][0]["name"]
    for i in range(M.MAX_ACCUSATIONS):
        r = client.post("/api/accuse", json={"suspect": other, "reasoning": f"guess {i}"})
        assert r.status_code == 200, r.text
        assert r.json()["accusations_left"] == M.MAX_ACCUSATIONS - 1 - i
    r = client.post("/api/accuse", json={"suspect": other, "reasoning": "one more"})
    assert r.status_code == 400
    assert r.json()["ok"] is False and "accusation" in r.json()["error"].lower()


def test_new_case_resets_casefile():
    _seed()
    M._API_KEY = None
    client.post("/api/inspect", json={"evidence_id": M._CASE["evidence"][0]["id"]})
    assert M.get_casefile()["probes_used"] >= 1
    r = client.post("/api/new-case", json={"difficulty": "Classic"}).json()
    assert r["ok"] is True
    assert r["casefile"]["probes_used"] == 0
    assert r["casefile"]["accusations_left"] == M.MAX_ACCUSATIONS


def test_unknown_ids_dont_consume_probe():
    _seed()
    M._API_KEY = None
    before = M.get_casefile()["probes_used"]
    client.post("/api/inspect", json={"evidence_id": "EX"})
    client.post("/api/search", json={"location": "Moon"})
    assert M.get_casefile()["probes_used"] == before
