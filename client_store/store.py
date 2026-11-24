from __future__ import annotations

import base64
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from cashflow_engine import FirmDefaults, Plan, project
from cashflow_engine.serialize import from_dict, plan_from_dict, plan_to_dict, to_dict

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS clients (
    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, data BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS plans (
    client_id TEXT NOT NULL REFERENCES clients(id), name TEXT NOT NULL,
    version INTEGER NOT NULL, saved_at TEXT NOT NULL, data BLOB NOT NULL,
    PRIMARY KEY (client_id, name, version));
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT, client_id TEXT, at TEXT NOT NULL, data BLOB NOT NULL);
"""

_CHECK = b"cashflow-planner"


class WrongPassphrase(Exception):
    pass


@dataclass
class AuditEntry:
    at: str
    client_id: str | None
    action: str
    detail: dict


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _key(passphrase: str, salt: bytes) -> bytes:
    kdf = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))


def _flatten(obj, prefix="") -> dict[str, object]:
    """Flatten a plan dict so two versions can be compared field by field."""
    out: dict[str, object] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_flatten(v, f"{prefix}{k}."))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            label = v.get("id") or v.get("name") if isinstance(v, dict) else None
            out.update(_flatten(v, f"{prefix}{label or i}."))
    else:
        out[prefix.rstrip(".")] = obj
    return out


def diff_plans(old: dict, new: dict) -> list[dict]:
    a, b = _flatten(old), _flatten(new)
    changes = []
    for k in sorted(a.keys() | b.keys()):
        if a.get(k) != b.get(k):
            changes.append({"field": k, "from": a.get(k), "to": b.get(k)})
    return changes


def _summary(plan: Plan) -> dict:
    f = project(plan)
    return {
        "final_age": f.final_age,
        "final_savings": round(f.final_savings, 2),
        "assets_run_out_at": f.assets_depletion_age(),
    }


class ClientStore:
    def __init__(self, path: str | Path, passphrase: str):
        self.path = Path(path)
        new = not self.path.exists()
        # The local web app serves requests from a thread pool; sqlite is built thread-safe.
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.executescript(SCHEMA)
        if new:
            os.chmod(self.path, 0o600)
        row = self.db.execute("SELECT value FROM meta WHERE key='salt'").fetchone()
        if row is None:
            salt = os.urandom(16)
            self.fernet = Fernet(_key(passphrase, salt))
            self.db.execute("INSERT INTO meta VALUES ('salt', ?)", (salt,))
            self.db.execute("INSERT INTO meta VALUES ('check', ?)", (self.fernet.encrypt(_CHECK),))
            self.db.commit()
        else:
            self.fernet = Fernet(_key(passphrase, row[0]))
            check = self.db.execute("SELECT value FROM meta WHERE key='check'").fetchone()[0]
            try:
                self.fernet.decrypt(check)
            except InvalidToken:
                self.db.close()
                raise WrongPassphrase("The passphrase is incorrect") from None

    # -- encryption helpers -------------------------------------------------
    def _enc(self, obj) -> bytes:
        return self.fernet.encrypt(json.dumps(obj, default=str).encode())

    def _dec(self, blob: bytes):
        return json.loads(self.fernet.decrypt(blob))

    def _audit(self, client_id: str | None, action: str, detail: dict) -> None:
        self.db.execute("INSERT INTO audit (client_id, at, data) VALUES (?, ?, ?)",
                        (client_id, _now(), self._enc({"action": action, "detail": detail})))

    # -- clients ------------------------------------------------------------
    def create_client(self, name: str, details: dict | None = None) -> str:
        cid = uuid.uuid4().hex
        self.db.execute("INSERT INTO clients VALUES (?, ?, ?)",
                        (cid, _now(), self._enc({"name": name, "details": details or {}})))
        self._audit(cid, "client created", {"name": name})
        self.db.commit()
        return cid

    def update_client(self, client_id: str, name: str | None = None, details: dict | None = None) -> None:
        current = self.get_client(client_id)
        new = {"name": name or current["name"], "details": details if details is not None else current["details"]}
        self.db.execute("UPDATE clients SET data=? WHERE id=?", (self._enc(new), client_id))
        self._audit(client_id, "client details changed",
                    {"changes": diff_plans(current, {**new, "id": client_id, "created_at": current["created_at"]})})
        self.db.commit()

    def get_client(self, client_id: str) -> dict:
        row = self.db.execute("SELECT created_at, data FROM clients WHERE id=?", (client_id,)).fetchone()
        if row is None:
            raise KeyError(client_id)
        return {"id": client_id, "created_at": row[0], **self._dec(row[1])}

    def list_clients(self) -> list[dict]:
        rows = self.db.execute("SELECT id, created_at, data FROM clients ORDER BY created_at").fetchall()
        return [{"id": r[0], "created_at": r[1], **self._dec(r[2])} for r in rows]

    # -- plans and scenarios ------------------------------------------------
    def save_plan(self, client_id: str, plan: Plan, note: str = "") -> int:
        """Save a new version of a plan (baseline or scenario, keyed by plan.name)."""
        self.get_client(client_id)
        data = plan_to_dict(plan)
        prev = self.db.execute(
            "SELECT version, data FROM plans WHERE client_id=? AND name=? ORDER BY version DESC LIMIT 1",
            (client_id, plan.name)).fetchone()
        version = 1 if prev is None else prev[0] + 1
        summary = _summary(plan)
        self.db.execute("INSERT INTO plans VALUES (?, ?, ?, ?, ?)",
                        (client_id, plan.name, version, _now(),
                         self._enc({"plan": data, "note": note, "summary": summary})))
        detail = {"plan": plan.name, "version": version, "note": note, "result": summary}
        if prev is not None:
            old = self._dec(prev[1])
            detail["changes"] = diff_plans(old["plan"], data)
            detail["previous_result"] = old["summary"]
            detail["impact_on_final_savings"] = round(
                summary["final_savings"] - old["summary"]["final_savings"], 2)
        self._audit(client_id, "plan saved", detail)
        self.db.commit()
        return version

    def load_plan(self, client_id: str, name: str = "Baseline", version: int | None = None) -> Plan:
        if version is None:
            row = self.db.execute(
                "SELECT data FROM plans WHERE client_id=? AND name=? ORDER BY version DESC LIMIT 1",
                (client_id, name)).fetchone()
        else:
            row = self.db.execute(
                "SELECT data FROM plans WHERE client_id=? AND name=? AND version=?",
                (client_id, name, version)).fetchone()
        if row is None:
            raise KeyError((client_id, name, version))
        return plan_from_dict(self._dec(row[0])["plan"])

    def plan_versions(self, client_id: str, name: str = "Baseline") -> list[dict]:
        rows = self.db.execute(
            "SELECT version, saved_at, data FROM plans WHERE client_id=? AND name=? ORDER BY version",
            (client_id, name)).fetchall()
        out = []
        for v, at, blob in rows:
            d = self._dec(blob)
            out.append({"version": v, "saved_at": at, "note": d["note"], "summary": d["summary"]})
        return out

    def plan_names(self, client_id: str) -> list[str]:
        rows = self.db.execute("SELECT DISTINCT name FROM plans WHERE client_id=? ORDER BY name",
                               (client_id,)).fetchall()
        return [r[0] for r in rows]

    # -- firm-wide default assumptions -----------------------------------------
    def get_defaults(self) -> FirmDefaults:
        row = self.db.execute("SELECT value FROM meta WHERE key='defaults'").fetchone()
        return FirmDefaults() if row is None else from_dict(FirmDefaults, self._dec(row[0]))

    def save_defaults(self, defaults: FirmDefaults, note: str = "") -> None:
        old = to_dict(self.get_defaults())
        new = to_dict(defaults)
        self.db.execute("INSERT OR REPLACE INTO meta VALUES ('defaults', ?)", (self._enc(new),))
        self._audit(None, "default assumptions changed", {"note": note, "changes": diff_plans(old, new)})
        self.db.commit()

    # -- audit --------------------------------------------------------------
    def audit_trail(self, client_id: str | None = None) -> list[AuditEntry]:
        q = "SELECT client_id, at, data FROM audit"
        args: tuple = ()
        if client_id:
            q += " WHERE client_id=?"
            args = (client_id,)
        out = []
        for cid, at, blob in self.db.execute(q + " ORDER BY id", args).fetchall():
            d = self._dec(blob)
            out.append(AuditEntry(at=at, client_id=cid, action=d["action"], detail=d["detail"]))
        return out

    def close(self) -> None:
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
