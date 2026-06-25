from utils.radial_menu_model import RingAccount, build_account_ring


def _account_for(views):
    return lambda aid: views.get(aid)


def test_builds_ring_in_recency_order_capped_at_8():
    ordered = [f"a{i}" for i in range(12)]
    views = {aid: ("ttr", f"Label {aid}") for aid in ordered}
    toons = {aid: ("Toon " + aid, "dna") for aid in ordered}
    ring = build_account_ring(
        ordered,
        account_for=_account_for(views),
        toon_for=lambda aid: toons.get(aid),
        is_running=lambda game, aid: False,
        limit=8,
    )
    assert [r.account_id for r in ring] == ordered[:8]
    assert ring[0] == RingAccount("a0", "ttr", "Label a0", "Toon a0", "dna", False)


def test_includes_running_accounts_flagged():
    ring = build_account_ring(
        ["a"],
        account_for=lambda aid: ("cc", "L"),
        toon_for=lambda aid: ("T", ""),
        is_running=lambda game, aid: True,
        limit=8,
    )
    assert ring[0].running is True


def test_missing_toon_yields_placeholder_entry():
    ring = build_account_ring(
        ["a"],
        account_for=lambda aid: ("ttr", "L"),
        toon_for=lambda aid: None,
        is_running=lambda game, aid: False,
        limit=8,
    )
    assert ring[0].toon_name is None and ring[0].dna == "" and ring[0].is_placeholder is True


def test_skips_deleted_accounts():
    ring = build_account_ring(
        ["gone", "ok"],
        account_for=lambda aid: None if aid == "gone" else ("ttr", "L"),
        toon_for=lambda aid: ("T", ""),
        is_running=lambda game, aid: False,
        limit=8,
    )
    assert [r.account_id for r in ring] == ["ok"]
