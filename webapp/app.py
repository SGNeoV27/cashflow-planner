"""Local web app: the adviser's screens on top of the engine, importer and store.

Run with ``python -m webapp``. It listens on 127.0.0.1 only, so it can't be
reached from other computers, and client data stays in the encrypted database
on this machine.
"""

from __future__ import annotations

import os
import tempfile
from datetime import date
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from cashflow_engine import project
from cashflow_engine.serialize import from_dict, plan_from_dict, plan_to_dict, to_dict
from client_store import ClientStore, WrongPassphrase
from fact_find_import import read_fact_find
from fact_find_import.factfind import FactFind
from fact_find_import.reader import UnknownFormat
from fact_find_import.to_plan import ImportDefaults, to_plan

STATIC = Path(__file__).parent / "static"
DEFAULT_DB = Path(os.environ.get("CASHFLOW_DB", Path.home() / "CashflowPlanner" / "clients.db"))

app = FastAPI(title="Cashflow Planner", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
_state: dict = {"store": None}


def store() -> ClientStore:
    s = _state["store"]
    if s is None:
        raise HTTPException(401, "Locked")
    return s


def forecast_json(plan) -> dict:
    f = project(plan)
    return {
        "plan_name": f.plan_name,
        "final_age": f.final_age,
        "final_savings": f.final_savings,
        "assets_run_out_at": f.assets_depletion_age(),
        "pots_run_out_at": {p.id: f.pot_depletion_age(p.id) for p in plan.pots},
        "pot_names": {p.id: p.name for p in plan.pots},
        "pot_types": {p.id: p.type.value for p in plan.pots},
        "rows": to_dict(f.rows),
    }


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


# -- unlock -----------------------------------------------------------------
@app.get("/api/status")
def status():
    return {"unlocked": _state["store"] is not None, "db_exists": DEFAULT_DB.exists(),
            "db_path": str(DEFAULT_DB)}


@app.post("/api/unlock")
def unlock(passphrase: str = Body(..., embed=True)):
    if len(passphrase) < 8:
        raise HTTPException(400, "Use a passphrase of at least 8 characters")
    DEFAULT_DB.parent.mkdir(parents=True, exist_ok=True)
    try:
        _state["store"] = ClientStore(DEFAULT_DB, passphrase)
    except WrongPassphrase:
        raise HTTPException(403, "Incorrect passphrase")
    return {"ok": True}


@app.post("/api/lock")
def lock():
    if _state["store"]:
        _state["store"].close()
    _state["store"] = None
    return {"ok": True}


# -- clients ----------------------------------------------------------------
@app.get("/api/clients")
def clients():
    return store().list_clients()


@app.post("/api/clients")
def create_client(body: dict = Body(...)):
    """Create a client with a blank baseline plan."""
    from cashflow_engine import Assumptions, Person, Plan, Pot, PotType

    dob = date.fromisoformat(body["date_of_birth"])
    plan = Plan(
        name="Baseline",
        client=Person(body["name"], dob, body.get("retirement_age")),
        start_date=date.fromisoformat(body.get("start_date") or date.today().isoformat()),
        pots=[Pot("current", "Current account", PotType.CURRENT_ACCOUNT, 0, growth_rate=0.005)],
        withdrawal_order=["current"],
        assumptions=Assumptions(),
    )
    cid = store().create_client(body["name"])
    store().save_plan(cid, plan, "Created")
    return {"id": cid}


@app.get("/api/clients/{cid}")
def client(cid: str):
    s = store()
    try:
        c = s.get_client(cid)
    except KeyError:
        raise HTTPException(404, "No such client")
    return {**c, "plans": s.plan_names(cid)}


@app.get("/api/clients/{cid}/plans/{name}")
def get_plan(cid: str, name: str, version: int | None = None):
    try:
        plan = store().load_plan(cid, name, version)
    except KeyError:
        raise HTTPException(404, "No such plan")
    return {"plan": plan_to_dict(plan), "versions": store().plan_versions(cid, name)}


@app.post("/api/clients/{cid}/plans")
def save_plan(cid: str, body: dict = Body(...)):
    plan = plan_from_dict(body["plan"])
    version = store().save_plan(cid, plan, body.get("note", ""))
    return {"version": version}


@app.get("/api/clients/{cid}/compare")
def compare(cid: str):
    s = store()
    return [forecast_json(s.load_plan(cid, n)) for n in s.plan_names(cid)]


@app.get("/api/clients/{cid}/audit")
def audit(cid: str):
    return to_dict(store().audit_trail(cid))


# -- forecasting ------------------------------------------------------------
@app.post("/api/project")
def run_forecast(plan: dict = Body(...)):
    try:
        return forecast_json(plan_from_dict(plan))
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(400, f"Plan is incomplete: {e}")


# -- fact-find import ---------------------------------------------------------
@app.post("/api/import")
async def import_pdf(file: UploadFile = File(...)):
    store()  # must be unlocked
    # The PDF is written to a private temporary file and deleted straight after reading.
    fd, tmp = tempfile.mkstemp(suffix=".pdf")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(await file.read())
        ff = read_fact_find(tmp)
    except UnknownFormat as e:
        raise HTTPException(400, str(e))
    finally:
        os.unlink(tmp)
    return {"fact_find": to_dict(ff), "defaults": to_dict(ImportDefaults())}


@app.post("/api/import/confirm")
def confirm_import(body: dict = Body(...)):
    ff = from_dict(FactFind, body["fact_find"])
    defaults = from_dict(ImportDefaults, body.get("defaults") or {}) if body.get("defaults") else None
    try:
        plan = to_plan(ff, start_date=date.fromisoformat(body["start_date"]),
                       date_of_birth=date.fromisoformat(body["date_of_birth"]) if body.get("date_of_birth") else None,
                       defaults=defaults)
    except ValueError as e:
        raise HTTPException(400, str(e))
    warnings = [w for w in ff.warnings if not (body.get("date_of_birth") and "date of birth" in w)]
    s = store()
    cid = s.create_client(plan.client.name, {
        "source": ff.source, "completed_on": str(ff.completed_on or ""),
        "objectives": ff.objectives, "notes": ff.notes,
        "other_assets": to_dict(ff.other_assets), "warnings": warnings,
    })
    s.save_plan(cid, plan, f"Imported from {ff.source} fact find")
    return {"id": cid}
