from helpers import fire, open_incidents
from rootfold.clock import FrozenClock
from rootfold.config import Settings
from rootfold.models import Alert


def test_child_alerts_fold_into_one_parent_incident(db, topology, clock: FrozenClock, settings: Settings) -> None:
    fire(db, clock, settings, "cir-ons-drm-mw", "circuit", "Microwave hop down")
    fire(db, clock, settings, "drm-rtr1", "device", "Router unreachable")
    fire(db, clock, settings, "drm-sw1", "device", "Switch unreachable")
    fire(db, clock, settings, "drm-backup", "device", "Backup job failed")
    inc = open_incidents(db)
    assert len(inc) == 1, [i.title for i in inc]
    parent = inc[0]
    assert parent.root_type == "circuit"
    assert parent.status == "open"
    assert parent.blast_radius is not None
    assert "drm" in parent.blast_radius["sites"]
    assert "cms" in parent.blast_radius["sites"]
    alerts = db.query(Alert).filter(Alert.incident_id == parent.id).all()
    assert len(alerts) == 4


def test_parent_arriving_late_merges_child_incidents(db, topology, clock: FrozenClock, settings: Settings) -> None:
    # Children fire first (common when ICMP to site devices fails at the same time).
    fire(db, clock, settings, "drm-rtr1", "device")
    fire(db, clock, settings, "drm-sw1", "device")
    # Two devices at the same site share the site as parent, so they may already
    # be two incidents (no site-level firing yet) or one — either way, the hop
    # arriving later must fold everything under the circuit.
    fire(db, clock, settings, "cir-ons-drm-mw", "circuit", "Microwave hop down")
    open_ = open_incidents(db)
    assert len(open_) == 1
    assert open_[0].root_type == "circuit"
    assert db.query(Alert).filter(Alert.incident_id == open_[0].id).count() == 3


def test_single_lacp_member_does_not_take_down_the_pop(db, topology, clock: FrozenClock, settings: Settings) -> None:
    fire(db, clock, settings, "cir-core-east", "circuit", "East member down")
    inc = open_incidents(db)
    assert len(inc) == 1
    assert inc[0].root_type == "circuit"
    # The far-side metro PoP is not folded in — the west member still carries the bundle.
    assert inc[0].root_type != "bundle"


def test_both_lacp_members_promote_to_bundle(db, topology, clock: FrozenClock, settings: Settings) -> None:
    fire(db, clock, settings, "cir-core-east", "circuit", "East member down")
    fire(db, clock, settings, "cir-core-west", "circuit", "West member down")
    inc = open_incidents(db)
    assert len(inc) == 1
    assert inc[0].root_type == "bundle"
    assert "bcu-pop" in (inc[0].blast_radius or {}).get("sites", [])
