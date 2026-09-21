"""Toon counters: the four per-toon counters on the Multitoon pinwheel card
(laff, beans on hand, bank, Cartoonival tokens) - the API parse, the tab's
state plumbing, and the wallet-tray / stacked layout switch.

Run via pytest with QT_QPA_PLATFORM=offscreen."""

from __future__ import annotations

import os
import sys

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")


# ── API parse ────────────────────────────────────────────────────────────────

def test_parse_tokens_accepts_bare_number_or_current_object():
    from utils.ttr_api import _parse_tokens
    assert _parse_tokens(389) == 389
    assert _parse_tokens(0) == 0
    assert _parse_tokens(12.0) == 12
    assert _parse_tokens({"current": 1204}) == 1204
    assert _parse_tokens({"current": 0}) == 0


def test_parse_tokens_absent_or_malformed_reads_as_none():
    """Presence-keyed: an absent field must NOT become a 0 (that would render
    a legitimate-looking "0 tokens" on every off-season toon)."""
    from utils.ttr_api import _parse_tokens
    assert _parse_tokens(None) is None
    assert _parse_tokens({}) is None
    assert _parse_tokens({"current": None}) is None
    assert _parse_tokens("389") is None
    assert _parse_tokens(True) is None


def test_get_toon_names_by_slot_returns_jar_bank_and_tokens(monkeypatch):
    """One /all.json payload -> (name, ..., beans on hand, bank, tokens), with
    beans now the JAR value (the old single counter reported the bank)."""
    import utils.ttr_api as api

    payload = {
        "toon": {"name": "Flossbud", "style": "dna", "headColor": "#abc"},
        "laff": {"current": 137, "max": 140},
        "beans": {"jar": {"current": 412, "max": 10000},
                  "bank": {"current": 6979, "max": 30000}},
        "tokens": 389,
    }
    monkeypatch.setattr(api, "_fetch_toon",
                        lambda port, timeout=5.0: payload if port == 1547 else None)
    monkeypatch.setattr(api, "_should_full_scan", lambda wids: True)
    monkeypatch.setattr(api, "_mark_full_scan_done", lambda wids: None)
    monkeypatch.setattr(api, "TTR_API_PORT_END", 1548)
    api._approved_ports.clear()

    res = api.get_toon_names_by_slot(2, None)
    assert len(res) == 8
    names, styles, colors, laffs, max_laffs, beans, bank, tokens = res
    assert names == ["Flossbud", None]
    assert laffs == [137, None] and max_laffs == [140, None]
    assert beans == [412, None]
    assert bank == [6979, None]
    assert tokens == [389, None]


def test_get_toon_names_by_slot_tokens_absent_is_none(monkeypatch):
    import utils.ttr_api as api

    payload = {
        "toon": {"name": "Flossbud"},
        "laff": {"current": 1, "max": 2},
        "beans": {"jar": {"current": 3}, "bank": {"current": 4}},
    }
    monkeypatch.setattr(api, "_fetch_toon",
                        lambda port, timeout=5.0: payload if port == 1547 else None)
    monkeypatch.setattr(api, "_should_full_scan", lambda wids: True)
    monkeypatch.setattr(api, "_mark_full_scan_done", lambda wids: None)
    monkeypatch.setattr(api, "TTR_API_PORT_END", 1548)
    api._approved_ports.clear()

    *_, beans, bank, tokens = api.get_toon_names_by_slot(1, None)
    assert (beans, bank, tokens) == ([3], [4], [None])


# ── Tab + layout ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


class _FakeWindowManager(QObject):
    window_ids_updated = Signal(list)

    def __init__(self):
        super().__init__()
        self.ttr_window_ids = []

    def get_window_ids(self):
        return list(self.ttr_window_ids)

    def clear_window_ids(self):
        self.ttr_window_ids = []

    def assign_windows(self):
        pass

    def enable_detection(self):
        pass

    def disable_detection(self):
        pass

    def get_active_window(self):
        return None


WIDS = ["w1", "w2", "w3", "w4"]


@pytest.fixture
def tab(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path))
    from tabs.multitoon._tab import MultitoonTab
    from utils.settings_manager import SettingsManager
    t = MultitoonTab(settings_manager=SettingsManager(),
                     window_manager=_FakeWindowManager())
    t.window_manager.ttr_window_ids = list(WIDS)
    t._last_window_ids = list(WIDS)
    t.resize(854, 840)
    t.show()
    for _ in range(3):
        qapp.processEvents()
    yield t
    t.close()


def _feed(tab, names, laffs=None, beans=None, bank=None, tokens=None):
    n = len(names)
    tab._apply_merged_toon_data(
        WIDS[:n], names, [None] * n, [None] * n,
        laffs or [140] * n, laffs or [140] * n,
        beans if beans is not None else [412] * n,
        bank if bank is not None else [6979] * n,
        tokens if tokens is not None else [389] * n,
    )
    QApplication.processEvents()


def _cell(tab, slot):
    layout = tab._compact
    return layout._cells[layout._slot_to_cell[slot]]


def test_bank_and_tokens_land_in_labels_with_thousands_separators(tab):
    _feed(tab, ["Flossbud"], beans=[412], bank=[6979], tokens=[1204])
    assert tab.bean_labels[0].text() == " 412"
    assert tab.bank_labels[0].text() == " 6,979"
    assert tab.token_labels[0].text() == " 1,204"
    assert not tab.bean_labels[0].isHidden()
    assert not tab.bank_labels[0].isHidden()
    assert not tab.token_labels[0].isHidden()
    assert tab.bean_labels[0].toolTip() == "Jellybeans on hand"
    assert tab.bank_labels[0].toolTip() == "Jellybeans in the bank"
    assert tab.token_labels[0].toolTip() == "Cartoonival Tokens"


def test_token_cell_keys_off_presence_not_value(tab):
    """0 renders as a legitimate "0 tokens"; None (CC toon / off-season)
    hides the cell - no dash, no zero, no placeholder."""
    _feed(tab, ["A", "B"], tokens=[0, None])
    assert not tab.token_labels[0].isHidden()
    assert tab.token_labels[0].text() == " 0"
    assert tab.token_labels[1].isHidden()
    # Tray still paints for slot 1 (it has beans + bank), just shorter.
    assert _cell(tab, 1)["meta_host"]._tray_on


def test_merged_data_without_bank_or_tokens_is_backwards_compatible(tab):
    """The 7-positional legacy call shape still works (bank/tokens absent)."""
    tab._apply_merged_toon_data(WIDS[:1], ["Legacy"], [None], [None], [50], [100], [25])
    QApplication.processEvents()
    assert tab.bean_labels[0].text() == " 25"
    assert tab.bank_labels[0].isHidden()
    assert tab.token_labels[0].isHidden()


def test_cc_slot_hides_all_four_counters(tab):
    from utils.cc_toon_info import CCToonInfo
    _feed(tab, ["Flossbud"])
    for lbl in tab._stat_labels(0):
        assert not lbl.isHidden()
    info = CCToonInfo(name="Hector", species_name="dog", species_emoji="?",
                      dna_colors=((0.4, 0.6, 0.3),) * 5)
    tab._apply_cc_toon_info([WIDS[0]], [info])
    QApplication.processEvents()
    for lbl in tab._stat_labels(0):
        assert lbl.isHidden()
    assert not _cell(tab, 0)["meta_host"]._tray_on


def test_short_name_uses_wallet_tray_and_laff_rides_the_name_line(tab):
    _feed(tab, ["Flossbud"])
    cell = _cell(tab, 0)
    assert cell["meta_stacked"] is False
    assert cell["meta_host"]._tray_on
    # Laff is in the name row; the three currencies are in the tray, in order.
    row_widgets = [cell["name_row"].itemAt(k).widget() for k in range(cell["name_row"].count())]
    assert tab.toon_labels[0][0] in row_widgets and tab.laff_labels[0] in row_widgets
    tray = [cell["tray_lay"].itemAt(k).widget() for k in range(cell["tray_lay"].count())]
    assert tray == [tab.bean_labels[0], tab.bank_labels[0], tab.token_labels[0]]
    assert cell["stack_r1"].count() == 0 and cell["stack_r2"].count() == 0


def test_long_name_stacks_two_lines_of_two(tab):
    """A name that would push laff off the name line re-renders as
    line 1 = live state (laff, beans), line 2 = stored totals (bank, tokens)."""
    _feed(tab, ["Gifted Every Strength Of Character"])
    cell = _cell(tab, 0)
    assert cell["meta_stacked"] is True
    assert not cell["meta_host"]._tray_on
    row = [cell["name_row"].itemAt(k).widget() for k in range(cell["name_row"].count())]
    assert row == [tab.toon_labels[0][0]]
    r1 = [cell["stack_r1"].itemAt(k).widget() for k in range(cell["stack_r1"].count())
          if cell["stack_r1"].itemAt(k).widget() is not None]
    r2 = [cell["stack_r2"].itemAt(k).widget() for k in range(cell["stack_r2"].count())
          if cell["stack_r2"].itemAt(k).widget() is not None]
    assert r1 == [tab.laff_labels[0], tab.bean_labels[0]]
    assert r2 == [tab.bank_labels[0], tab.token_labels[0]]
    assert cell["tray_lay"].count() == 0


def test_wide_tray_stacks_even_with_a_short_name(tab):
    """Big balances can make the capsule wider than the clearance box; that
    stacks too rather than sliding under the emblem or widening the card."""
    min_w = tab.minimumSizeHint().width()
    _feed(tab, ["Zip"], beans=[2_678], bank=[150_000], tokens=[12_345])
    cell = _cell(tab, 0)
    assert cell["meta_stacked"] is True
    assert tab.minimumSizeHint().width() == min_w


def test_switch_is_width_driven_not_a_name_length_rule(tab, qapp):
    """The same toon stacks on a narrow card and gets the tray back on a
    wider one."""
    name = "Gifted Every Strength"
    _feed(tab, [name])
    cell = _cell(tab, 0)
    assert cell["meta_stacked"] is True
    tab.resize(1400, 840)
    for _ in range(3):
        qapp.processEvents()
    assert cell["meta_stacked"] is False
    tab.resize(854, 840)
    for _ in range(3):
        qapp.processEvents()
    assert cell["meta_stacked"] is True


def test_layout_switch_never_changes_card_height(tab, qapp):
    layout = tab._compact
    _feed(tab, ["Zip"])
    tray_h = layout.card_size()[1]
    assert _cell(tab, 0)["meta_stacked"] is False
    _feed(tab, ["Gifted Every Strength Of Character"])
    assert _cell(tab, 0)["meta_stacked"] is True
    assert layout.card_size()[1] == tray_h


def test_counters_arriving_never_widen_the_window(tab, qapp):
    """Routing happens BEFORE the labels are shown: a tray that is about to
    stack must not first push the window's minimum width (a top-level
    window never gives that back)."""
    width, min_w = tab.width(), tab.minimumSizeHint().width()
    _feed(tab, ["Gifted Every Strength", "Zip"],
          beans=[2678, 0], bank=[15000, 0], tokens=[1204, 0])
    for _ in range(3):
        qapp.processEvents()
    assert tab.width() == width
    assert tab.minimumSizeHint().width() == min_w


def test_all_four_counters_take_the_dim_stat_style(tab):
    layout = tab._compact
    layout.set_card_brand(0, "ttr", enabled=False)
    qss = {lbl.styleSheet() for lbl in tab._stat_labels(0)}
    assert len(qss) == 1, "laff/beans/bank/tokens must share one stat style"
    assert "min-height: 22px" in qss.pop()


def test_meta_host_does_not_report_the_full_name_width(tab):
    """An eliding name's sizeHint is its full text width; the meta host must
    not pass that up, or card_size() would widen every overlay surface."""
    card_w = tab._compact.card_size()[0]
    _feed(tab, ["An Extraordinarily Long Toon Name Indeed"])
    cell = _cell(tab, 0)
    assert cell["meta_host"].sizeHint().width() == cell["meta_host"].minimumSizeHint().width()
    assert tab._compact.card_size()[0] == card_w
