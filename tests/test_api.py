"""Validation, no-leak, and state-machine tests (mocked case, no network)."""
from fastapi.testclient import TestClient

import app as M


def _seed():
    M._CASE = M.create_fallback_case("Classic")
    M._PROGRESS = {"found_evidence": [], "searched_locations": [], "questioned": []}
    M._ACCUSED = None
    return M._CASE


client = TestClient(M.app)


def test_redact_never_leaks_culprit():
    case = _seed()
    pub = M.redact_case(case)
    # suspect names are public (needed to accuse); but solution/secret must not leak
    assert "culprit" not in pub and "solution_summary" not in pub
    blob = str(pub)
    assert case["solution_summary"] not in blob
    for s in case["suspects"]:
        assert s["secret"] not in blob
    for e in case["evidence"]:
        assert e["detail"] not in blob


def test_no_leak_interrogate_offline():
    case = _seed()
    M._API_KEY = None  # force offline branch (direct function, no network)
    others = [s for s in case["suspects"] if s["name"] != case["culprit"]]
    # interrogate a non-culprit: response must not contain culprit name
    r = client.post("/api/interrogate", json={"suspect": others[0]["name"], "question": "Where were you?"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert case["culprit"] not in body["answer"]


def test_no_leak_search_inspect():
    case = _seed()
    for loc in case["locations"]:
        r = client.post("/api/search", json={"location": loc["name"]})
        assert r.json()["ok"] is True
        for c in r.json()["clues"]:
            assert case["culprit"] not in c
    for e in case["evidence"]:
        r = client.post("/api/inspect", json={"evidence_id": e["id"]})
        assert r.json()["ok"] is True
        assert case["culprit"] not in r.json()["evidence"]["detail"]


def test_validation_everywhere():
    _seed()
    assert client.post("/api/new-case", json={"difficulty": "Impossible"}).json()["ok"] is False
    assert client.post("/api/interrogate", json={"suspect": "Nobody", "question": "hi"}).json()["ok"] is False
    assert client.post("/api/inspect", json={"evidence_id": "EX"}).json()["ok"] is False
    assert client.post("/api/search", json={"location": "Moon"}).json()["ok"] is False
    assert client.post("/api/accuse", json={"suspect": "Nobody", "reasoning": "x"}).json()["ok"] is False


def test_state_machine_accuse_reveal():
    case = _seed()
    # correct accusation wins
    r = client.post("/api/accuse", json={"suspect": case["culprit"], "reasoning": "fishing line + footprint"})
    assert r.json()["ok"] is True and r.json()["win"] is True
    # wrong accusation loses
    other = [s for s in case["suspects"] if s["name"] != case["culprit"]][0]
    r2 = client.post("/api/accuse", json={"suspect": other["name"], "reasoning": "guess"})
    assert r2.json()["ok"] is True and r2.json()["win"] is False
    # culprit constant: reveal matches stored case
    rev = client.post("/api/reveal").json()
    assert rev["ok"] is True and rev["culprit"] == case["culprit"]
    # progress tracker moves
    client.post("/api/inspect", json={"evidence_id": case["evidence"][0]["id"]})
    st = client.get("/api/state").json()
    assert st["progress"]["clues_found"] >= 1


def test_parse_case_json_rejects_bad_shape():
    import pytest

    with pytest.raises(Exception):
        M.parse_case_json('{"bad": 1}')
