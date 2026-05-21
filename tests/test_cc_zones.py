from utils import cc_zones


def test_known_hood_id_resolves_to_playground():
    # hood_id 2000 confirmed = Toontown Central (from CC stdout captures)
    playground, zone = cc_zones.lookup(zone_id=2000, hood_id=2000)
    assert playground == "Toontown Central"
    # When zone_id == hood_id, the toon is at the playground itself
    # (no specific street). zone returns None so the chip row shows
    # the playground chip only.
    assert zone is None


def test_unknown_zone_id_known_hood_returns_playground_only():
    # If hood is mapped but zone isn't, fall back to playground-only.
    playground, zone = cc_zones.lookup(zone_id=9999999, hood_id=2000)
    assert playground == "Toontown Central"
    assert zone is None


def test_unknown_hood_returns_both_none():
    playground, zone = cc_zones.lookup(zone_id=9999999, hood_id=8888888)
    assert playground is None
    assert zone is None


def test_unknown_hood_logs_once(caplog, monkeypatch):
    monkeypatch.setattr(cc_zones, "_logged_unknown_hoods", set())
    with caplog.at_level("INFO"):
        cc_zones.lookup(zone_id=0, hood_id=88888)
        cc_zones.lookup(zone_id=0, hood_id=88888)
    assert sum(1 for r in caplog.records if "unknown hood id" in r.message) == 1
