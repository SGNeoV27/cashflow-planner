"""API smoke test: unlock, import, edit, scenario, compare, audit."""

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fact_find_import.cashcalc import parse_cashcalc
from cashflow_engine.serialize import to_dict
from cashflow_engine import FirmDefaults

SAMPLE = Path(__file__).parent / "data" / "cashcalc_sample.txt"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CASHFLOW_DB", str(tmp_path / "clients.db"))
    import webapp.app as appmod
    appmod = importlib.reload(appmod)
    with TestClient(appmod.app) as c:
        yield c
    if appmod._state["store"]:
        appmod._state["store"].close()


def test_locked_until_unlocked(client):
    assert client.get("/api/clients").status_code == 401
    assert client.post("/api/unlock", json={"passphrase": "short"}).status_code == 400
    assert client.post("/api/unlock", json={"passphrase": "a good passphrase"}).status_code == 200
    assert client.get("/api/clients").json() == []
    client.post("/api/lock", json={})
    assert client.post("/api/unlock", json={"passphrase": "wrong passphrase"}).status_code == 403


def test_import_edit_and_compare(client):
    client.post("/api/unlock", json={"passphrase": "a good passphrase"})
    ff = to_dict(parse_cashcalc(SAMPLE.read_text()))
    r = client.post("/api/import/confirm", json={
        "fact_find": ff, "atr": 6,
        "date_of_birth": "1965-01-07", "start_date": "2021-10-19"})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    info = client.get(f"/api/clients/{cid}").json()
    assert info["name"] == "Test Client"
    assert not any("date of birth" in w for w in info["details"]["warnings"])

    plan = client.get(f"/api/clients/{cid}/plans/Baseline").json()["plan"]
    assert {p["growth_rate"] for p in plan["pots"] if p["type"] == "pension"} == {0.045}  # ATR 6 central
    assert plan["assumptions"]["inflation"] == 0.02
    f = client.post("/api/project", json=plan).json()
    assert f["rows"][0]["savings_start"] == pytest.approx(376_300)

    plan["name"] = "Inflation 4%"
    plan["assumptions"]["inflation"] = 0.04
    assert client.post(f"/api/clients/{cid}/plans", json={"plan": plan, "note": "test"}).json()["version"] == 1
    names = [x["plan_name"] for x in client.get(f"/api/clients/{cid}/compare").json()]
    assert names == ["Baseline", "Inflation 4%"]
    actions = [e["action"] for e in client.get(f"/api/clients/{cid}/audit").json()]
    assert actions == ["client created", "plan saved", "plan saved"]


def test_bad_plan_rejected(client):
    client.post("/api/unlock", json={"passphrase": "a good passphrase"})
    assert client.post("/api/project", json={"client": {}}).status_code == 400


def test_settings_edit_and_reset(client):
    client.post("/api/unlock", json={"passphrase": "a good passphrase"})
    d = client.get("/api/settings").json()
    assert d["atr_table"]["1"]["central"] == 0.02 and d["product_returns"] == {"Premium Bonds": 0.0}
    d["inflation"] = 0.03
    assert client.post("/api/settings", json={"defaults": d, "note": "test"}).status_code == 200
    assert client.get("/api/settings").json()["inflation"] == 0.03
    del d["atr_table"]["10"]
    assert client.post("/api/settings", json={"defaults": d}).status_code == 400
    assert client.post("/api/settings/reset", json={}).json()["inflation"] == 0.02
