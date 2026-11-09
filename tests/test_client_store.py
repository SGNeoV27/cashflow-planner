import pytest

from cashflow_engine import long_term_care
from client_store import ClientStore, WrongPassphrase
from fixtures import voyant_baseline_plan

PASS = "correct horse battery staple"


@pytest.fixture
def store(tmp_path):
    s = ClientStore(tmp_path / "clients.db", PASS)
    yield s
    s.close()


def test_nothing_readable_on_disk(tmp_path):
    path = tmp_path / "clients.db"
    with ClientStore(path, PASS) as s:
        cid = s.create_client("Test Client A", {"notes": "very private"})
        s.save_plan(cid, voyant_baseline_plan())
    raw = path.read_bytes()
    for secret in (b"Test Client A", b"very private", b"Council Tax", b"376300"):
        assert secret not in raw


def test_wrong_passphrase_rejected(tmp_path):
    path = tmp_path / "clients.db"
    ClientStore(path, PASS).close()
    with pytest.raises(WrongPassphrase):
        ClientStore(path, "wrong")
    ClientStore(path, PASS).close()  # still opens with the right one


def test_save_and_load_plan_versions(store):
    cid = store.create_client("Test Client A")
    plan = voyant_baseline_plan()
    plan.name = "Baseline"
    assert store.save_plan(cid, plan, "From fact find") == 1
    plan.assumptions.inflation = 0.03
    assert store.save_plan(cid, plan, "Inflation to 3%") == 2

    assert store.load_plan(cid).assumptions.inflation == 0.03
    assert store.load_plan(cid, version=1).assumptions.inflation == 0.02  # old assumptions kept
    versions = store.plan_versions(cid)
    assert [v["note"] for v in versions] == ["From fact find", "Inflation to 3%"]


def test_audit_records_changes_and_impact(store):
    cid = store.create_client("Test Client A")
    plan = voyant_baseline_plan()
    plan.name = "Baseline"
    store.save_plan(cid, plan)
    plan.pot("isa").growth_rate = 0.03
    store.save_plan(cid, plan, "ISA return to 3%")

    entry = store.audit_trail(cid)[-1]
    assert entry.action == "plan saved"
    assert {"field": "pots.isa.growth_rate", "from": 0.01, "to": 0.03} in entry.detail["changes"]
    assert entry.detail["impact_on_final_savings"] > 0
    assert [e.action for e in store.audit_trail(cid)] == ["client created", "plan saved", "plan saved"]


def test_scenarios_saved_separately(store):
    cid = store.create_client("Test Client A")
    base = voyant_baseline_plan()
    base.name = "Baseline"
    store.save_plan(cid, base)
    store.save_plan(cid, long_term_care(60_000, 85).apply(base))
    assert store.plan_names(cid) == ["Baseline", "Long-term care from 85"]
    assert len(store.load_plan(cid, "Long-term care from 85").expenses) == len(base.expenses) + 1


def test_list_and_update_clients(store):
    a = store.create_client("Client A")
    store.create_client("Client B")
    store.update_client(a, details={"retirement_age": 60})
    assert [c["name"] for c in store.list_clients()] == ["Client A", "Client B"]
    assert store.get_client(a)["details"] == {"retirement_age": 60}
    assert store.audit_trail(a)[-1].action == "client details changed"
