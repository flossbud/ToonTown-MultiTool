"""What the classic Multitoon tab's tests pinned, checked on ToonSession.

The tab's sleep-inhibitor, render-cache discovery and log-level tests go
when the tab goes. ToonSession (and the launchpad window around it) carry
the same behaviour; these keep it pinned under the session's own names.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TTMT_NO_VENV_REEXEC", "1")

import inspect
import time
from types import SimpleNamespace

import pytest

from tests.test_render_cache_triggers import facade  # noqa: F401  (fixture)
from tests.toon_session_harness import KEEP_ALIVE_ON, Rig


@pytest.fixture
def make(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("TTMT_CONFIG_DIR", str(tmp_path / "config"))
    made = []

    def _make(**kwargs):
        made.append(Rig(tmp_path, **kwargs))
        return made[-1]

    yield _make
    for rig in made:
        rig.close()


def _wait_for(qapp, until, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if until():
            return True
        time.sleep(0.01)
    return False


# ── Sleep inhibitor ────────────────────────────────────────────────────────

def test_an_unverified_inhibitor_is_a_warning(make, qapp):
    """Acquire could not hold sleep off: the status still goes out (the
    window warns the user once), and the log says so at warn level."""
    levels = []
    rig = make(settings={**KEEP_ALIVE_ON, "keep_alive_delay": "10 min"})
    rig.session._logger = SimpleNamespace(
        append_log=lambda msg, level=None: levels.append((msg, level)))
    rig.inhibitor.status = SimpleNamespace(sleep_blocked=False, method=None)
    statuses = []
    rig.session.keep_alive_inhibit_status.connect(statuses.append)
    rig.wm.set_windows(["a"])
    rig.session.set_keep_alive("a", True)
    assert _wait_for(qapp, lambda: statuses)
    assert statuses == [rig.inhibitor.status]
    warned = [lvl for msg, lvl in levels if "could not verify sleep inhibitor" in msg.lower()]
    assert warned == ["warn"]


def test_release_frees_the_inhibitor_even_if_it_never_reported(make):
    """An acquire still running when the loop stops may take a hold after
    the session last looked; release is therefore unconditional, so nothing
    is left holding sleep off."""
    rig = make(settings={**KEEP_ALIVE_ON, "keep_alive_delay": "10 min"})
    rig.session._release_sleep_inhibitor()            # nothing acquired yet
    assert rig.inhibitor.calls == ["release"]


# ── Render cache discovery ─────────────────────────────────────────────────

def test_discovery_reaches_the_render_cache_with_the_windows_game(make, facade, monkeypatch):
    f, _store, _pf, _tmp = facade
    seen = []
    monkeypatch.setattr(f, "discovered", lambda g, n, d: seen.append((g, n, d)))
    rig = make()
    rig.wm.set_windows(["a"])
    rig.ttr("a", "Hiro", dna="dna1", laff=10)
    assert seen == [("ttr", "Hiro", "dna1")]
    rig.ttr("a", "Hiro", dna="", laff=10)               # no DNA: nothing to fetch
    assert seen == [("ttr", "Hiro", "dna1")]


def test_discovery_runs_again_only_when_something_changed(make, facade, monkeypatch):
    f, _store, _pf, _tmp = facade
    seen = []
    monkeypatch.setattr(f, "discovered", lambda g, n, d: seen.append((g, n, d)))
    rig = make()
    rig.wm.set_windows(["a", "b"])
    for _ in range(3):
        rig.ttr("a", "Hiro", dna="dna1", laff=10)        # every poll, same toon
    assert seen == [("ttr", "Hiro", "dna1")]
    rig.ttr("a", "Hiro", dna="dna2", laff=10)            # a new outfit
    assert seen[-1] == ("ttr", "Hiro", "dna2")
    rig.ttr("b", "Hiro", dna="dna2", laff=10)            # same toon, another window
    assert len(seen) == 3


def test_a_clash_toon_has_no_dna_to_discover(make, facade, monkeypatch):
    f, _store, _pf, _tmp = facade
    seen = []
    monkeypatch.setattr(f, "discovered", lambda g, n, d: seen.append((g, n, d)))
    rig = make()
    rig.wm.set_windows(["c"], games={"c": "cc"})
    rig.cc("c", SimpleNamespace(name="Moe", species_name="Dog", dna_colors=[(1.0, 0.0, 0.0)]))
    assert rig.session.toon("c").name == "Moe"
    assert seen == []


# ── Log levels ─────────────────────────────────────────────────────────────

def test_the_session_log_passes_the_level_through(make):
    calls = []
    rig = make()
    rig.session._logger = SimpleNamespace(
        append_log=lambda msg, level=None: calls.append((msg, level)))
    rig.session._log("boom", level="warn")
    rig.session._log("plain")
    assert calls == [("boom", "warn"), ("plain", None)]
    level = inspect.signature(type(rig.session)._log).parameters["level"]
    assert level.default is None


def test_the_window_log_passes_the_level_through():
    from utils.launchpad_window import LaunchpadWindow
    calls = []
    win = SimpleNamespace(debug_tab=SimpleNamespace(
        logging_enabled=True,
        append_log=lambda msg, level=None: calls.append((msg, level))))
    LaunchpadWindow.log(win, "boom", level="warn")
    assert calls == [("boom", "warn")]
    level = inspect.signature(LaunchpadWindow.log).parameters["level"]
    assert level.default is None
