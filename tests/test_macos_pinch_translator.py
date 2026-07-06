"""macOS pinch translator suite - decoder + factor-stream section.

Pins the DARWIN wire semantics of utils/overlay/macos_pinch.py against the
CP-P1 run-3 captures (tests/fixtures/pinch/*.json, wholesale copies of
docs/superpowers/specs/pinch-probe-raw/cp_p1_run3_field_dump.log - the
probe ledger's decoded format is BINDING). The decoder half is platform-pure
(no Quartz, no Qt), so this file runs offscreen on any platform; the tap-
lifecycle tests (mocked Quartz, darwin-pinned) land in a follow-on task.

Golden final factors are computed HERE from the raw fixture fields with the
same product formula, so a decoder/stream regression cannot self-confirm
through values the implementation produced.

Run (NEVER the whole tests/ dir):
    TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen \
        PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
        ./venv/bin/python -m pytest tests/test_macos_pinch_translator.py -q
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

import utils.overlay.macos_pinch as macos_pinch
from utils.overlay.macos_pinch import (
    CG_TYPE_GESTURE,
    CG_TYPE_MAGNIFY,
    FIELD_CUMULATIVE,
    FIELD_DELTA,
    FIELD_PHASE,
    FIELD_SUBTYPE,
    PHASE_BEGAN,
    PHASE_CHANGED,
    PHASE_ENDED,
    SUBTYPE_ZOOM,
    MacOSPinchTranslator,
    PinchEvent,
    PinchFactorStream,
    PinchKind,
    decode_cg_event,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_DIR = os.path.join(REPO_ROOT, "tests", "fixtures", "pinch")


def _load(name):
    """Fixture events as (cgType, fields) with INT field-number keys - JSON
    forces string keys, the decoder takes the numeric CGEvent field numbers
    the live tap glue will use."""
    with open(os.path.join(FIXTURE_DIR, name)) as fh:
        fixture = json.load(fh)
    events = [(e["cgType"], {int(k): v for k, v in e["fields"].items()})
              for e in fixture["events"]]
    return fixture["metadata"], events


def _zoom_deltas(events):
    """Raw d113 stream of the i110=8 events, straight from fixture fields
    (independent of the decoder)."""
    return [f[FIELD_DELTA] for t, f in events
            if t == CG_TYPE_GESTURE and f.get(FIELD_SUBTYPE) == SUBTYPE_ZOOM]


def _product_factor(deltas):
    factor = 1.0
    for delta in deltas:
        factor *= (1.0 + delta)
    return factor


class _Recorder:
    """Callback recorder: the stream's begin/update/end calls land in
    ``calls`` in order, so tests can pin the exact emission sequence."""

    def __init__(self):
        self.calls = []
        self.stream = PinchFactorStream(
            on_begin=lambda: self.calls.append(("begin",)),
            on_update=lambda factor: self.calls.append(("update", factor)),
            on_end=lambda cancelled: self.calls.append(("end", cancelled)),
        )

    def feed_all(self, events):
        for etype, fields in events:
            self.stream.feed(decode_cg_event(etype, fields))

    @property
    def updates(self):
        return [c[1] for c in self.calls if c[0] == "update"]


def _ev(kind, value, cumulative=False):
    return PinchEvent(kind=kind, value=value, cumulative=cumulative)


# ── Purity ───────────────────────────────────────────────────────────────────

class TestPurity:
    def test_import_pulls_no_quartz_and_no_qt(self):
        """The decoder half must be importable everywhere: Quartz only ever
        loads inside the translator's tap methods (follow-on task), and Qt
        never. Subprocess: this pytest process already has PySide6 loaded via
        conftest, so only a fresh interpreter proves the import is clean."""
        code = (
            "import sys; import utils.overlay.macos_pinch; "
            "leaked = [m for m in sys.modules "
            "          if 'Quartz' in m or 'PySide6' in m]; "
            "assert not leaked, f'native modules leaked: {leaked}'"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, result.stderr


# ── Fixture: positive i110=8 gesture ─────────────────────────────────────────

class TestPositiveZoomFixture:
    NAME = "cp_p1_positive_zoom.json"

    def test_provenance(self):
        metadata, _ = _load(self.NAME)
        assert metadata["source_log"].endswith("cp_p1_run3_field_dump.log")
        assert metadata["cgtype"] == CG_TYPE_GESTURE

    def test_decode_counts_and_kind_sequence(self):
        _, events = _load(self.NAME)
        decoded = [decode_cg_event(t, f) for t, f in events]
        pinch = [d for d in decoded if d is not None]
        # 9 zoom events among 25 captured tap lines: the interleaved family
        # noise (i110=4 / subtype-less) must vanish in the same pass.
        assert len(events) == 25
        assert [d.kind for d in pinch] == (
            [PinchKind.BEGIN] + [PinchKind.DELTA] * 7 + [PinchKind.END])
        assert all(not d.cumulative for d in pinch)

    def test_stream_emission_and_exact_final_factor(self):
        _, events = _load(self.NAME)
        deltas = _zoom_deltas(events)
        golden = _product_factor(deltas)   # independent of the decoder
        rec = _Recorder()
        rec.feed_all(events)
        # Began carries a real delta, so begin emits its own update; the
        # Ended delta is applied AND published before end fires.
        assert rec.calls[0] == ("begin",)
        assert rec.calls[-1] == ("end", False)
        assert len(rec.updates) == len(deltas)
        assert rec.updates[-1] == golden
        assert golden > 1.0   # fingers apart: factor direction pinned


# ── Fixture: negative i110=8 gesture ─────────────────────────────────────────

class TestNegativeZoomFixture:
    NAME = "cp_p1_negative_zoom.json"

    def test_decode_counts_and_kind_sequence(self):
        _, events = _load(self.NAME)
        pinch = [d for d in (decode_cg_event(t, f) for t, f in events)
                 if d is not None]
        assert [d.kind for d in pinch] == (
            [PinchKind.BEGIN] + [PinchKind.DELTA] * 9 + [PinchKind.END])

    def test_stream_emission_and_exact_final_factor(self):
        _, events = _load(self.NAME)
        deltas = _zoom_deltas(events)
        golden = _product_factor(deltas)
        rec = _Recorder()
        rec.feed_all(events)
        assert rec.calls[0] == ("begin",)
        assert rec.calls[-1] == ("end", False)
        assert len(rec.updates) == len(deltas)
        assert rec.updates[-1] == golden
        assert golden < 1.0   # fingers together: factor direction pinned


# ── Fixture: THE cgType=30 gesture (cumulative d124) ─────────────────────────

class TestType30CumulativeFixture:
    NAME = "cp_p1_type30_cumulative.json"

    def test_decode_counts_and_kind_sequence(self):
        metadata, events = _load(self.NAME)
        assert metadata["cgtype"] == CG_TYPE_MAGNIFY
        decoded = [decode_cg_event(t, f) for t, f in events]
        pinch = [d for d in decoded if d is not None]
        # 5 magnify events; the interleaved cgType=29 subtype-less family
        # lines in the same slice decode to None.
        assert len(pinch) == 5
        assert [d.kind for d in pinch] == (
            [PinchKind.BEGIN] + [PinchKind.DELTA] * 3 + [PinchKind.END])
        assert all(d.cumulative for d in pinch)

    def test_stream_differences_cumulative_and_exact_final_factor(self):
        _, events = _load(self.NAME)
        cumulatives = [f[FIELD_CUMULATIVE] for t, f in events
                       if t == CG_TYPE_MAGNIFY]
        # Independent golden: successive d124 differences, previous value
        # reset to 0.0 at Began (the Began cumulative IS its own delta -
        # run 3's d126=|delta| equals |d124| on that line).
        golden, previous = 1.0, 0.0
        for cumulative in cumulatives:
            golden *= (1.0 + (cumulative - previous))
            previous = cumulative
        rec = _Recorder()
        rec.feed_all(events)
        assert rec.calls[0] == ("begin",)
        assert rec.calls[-1] == ("end", False)
        assert len(rec.updates) == len(cumulatives)
        assert rec.updates[-1] == golden
        assert golden < 1.0   # the captured type-30 gesture was a zoom-out


# ── Fixture: noise subtypes decode to nothing ────────────────────────────────

class TestNoiseFixture:
    NAME = "cp_p1_noise_subtypes.json"

    def test_every_event_decodes_to_none(self):
        _, events = _load(self.NAME)
        assert len(events) == 58
        subtypes = {f.get(FIELD_SUBTYPE) for _, f in events}
        # The slice really exercises every observed non-zoom subtype, plus
        # subtype-less family lines - never SUBTYPE_ZOOM.
        assert {4, 5, 6, 32, None} <= subtypes
        assert SUBTYPE_ZOOM not in subtypes
        assert all(decode_cg_event(t, f) is None for t, f in events)

    def test_stream_stays_silent_end_to_end(self):
        _, events = _load(self.NAME)
        rec = _Recorder()
        rec.feed_all(events)
        assert rec.calls == []
        assert not rec.stream.in_gesture

    def test_collision_line_kept_double_value(self):
        """Curation pin: where the capture printed both i116 and d116, the
        fixture keeps the DOUBLE (metadata field_map_note rule)."""
        _, events = _load(self.NAME)
        collision = [f for _, f in events if 116 in f and f.get(110) == 5]
        assert any(f[116] == -1.83071 for f in collision)


# ── decode_cg_event unit behavior ────────────────────────────────────────────

class TestDecodeUnit:
    ZOOM_FIELDS = {FIELD_SUBTYPE: SUBTYPE_ZOOM, FIELD_DELTA: 0.05,
                   FIELD_PHASE: PHASE_CHANGED}

    def test_wrong_cg_type_is_none(self):
        assert decode_cg_event(22, dict(self.ZOOM_FIELDS)) is None

    @pytest.mark.parametrize("subtype", [4, 5, 6, 32, 23])
    def test_type29_non_zoom_subtype_is_none(self, subtype):
        fields = dict(self.ZOOM_FIELDS)
        fields[FIELD_SUBTYPE] = subtype
        assert decode_cg_event(CG_TYPE_GESTURE, fields) is None

    @pytest.mark.parametrize("missing", [FIELD_SUBTYPE, FIELD_DELTA,
                                         FIELD_PHASE])
    def test_type29_missing_field_is_none(self, missing):
        fields = dict(self.ZOOM_FIELDS)
        del fields[missing]
        assert decode_cg_event(CG_TYPE_GESTURE, fields) is None

    @pytest.mark.parametrize("missing", [FIELD_CUMULATIVE, FIELD_PHASE])
    def test_type30_missing_field_is_none(self, missing):
        fields = {FIELD_CUMULATIVE: -0.1, FIELD_PHASE: PHASE_CHANGED}
        del fields[missing]
        assert decode_cg_event(CG_TYPE_MAGNIFY, fields) is None

    def test_empty_fields_are_none_for_both_types(self):
        assert decode_cg_event(CG_TYPE_GESTURE, {}) is None
        assert decode_cg_event(CG_TYPE_MAGNIFY, {}) is None

    def test_type30_needs_no_subtype(self):
        """i110 read 23 on the one captured type-30 gesture; the decoder
        keys on cgType+d124 only (pinning one capture's subtype would
        overfit)."""
        event = decode_cg_event(
            CG_TYPE_MAGNIFY,
            {FIELD_CUMULATIVE: -0.1, FIELD_PHASE: PHASE_BEGAN})
        assert event == _ev(PinchKind.BEGIN, -0.1, cumulative=True)

    def test_phase_mapping(self):
        for phase, kind in ((PHASE_BEGAN, PinchKind.BEGIN),
                            (PHASE_CHANGED, PinchKind.DELTA),
                            (PHASE_ENDED, PinchKind.END)):
            fields = dict(self.ZOOM_FIELDS)
            fields[FIELD_PHASE] = phase
            event = decode_cg_event(CG_TYPE_GESTURE, fields)
            assert event == _ev(kind, 0.05)

    @pytest.mark.parametrize("phase", [8, 128, 3, 5])
    def test_unknown_nonzero_phase_maps_to_cancel(self, phase):
        """Cancelled was never observed live: any unrecognized nonzero phase
        terminates conservatively (ledger rule)."""
        fields = dict(self.ZOOM_FIELDS)
        fields[FIELD_PHASE] = phase
        assert decode_cg_event(CG_TYPE_GESTURE, fields).kind \
            is PinchKind.CANCEL
        assert decode_cg_event(
            CG_TYPE_MAGNIFY,
            {FIELD_CUMULATIVE: -0.1, FIELD_PHASE: phase},
        ).kind is PinchKind.CANCEL

    def test_phase_zero_is_none(self):
        # Phase 0 = no gesture phase: not an event, not a cancel.
        fields = dict(self.ZOOM_FIELDS)
        fields[FIELD_PHASE] = 0
        assert decode_cg_event(CG_TYPE_GESTURE, fields) is None


# ── PinchFactorStream unit behavior ──────────────────────────────────────────

class TestStreamUnit:
    def test_feed_none_is_noop(self):
        rec = _Recorder()
        rec.stream.feed(None)
        assert rec.calls == []

    @pytest.mark.parametrize("kind", [PinchKind.DELTA, PinchKind.END,
                                      PinchKind.CANCEL])
    def test_orphan_events_dropped_silently(self, kind):
        """No begin -> a bare changed/end/cancel is dropped: opening a
        gesture on partial evidence would bypass the coordinator's begin
        gate, and the machine already defines stray updates as no-ops."""
        rec = _Recorder()
        rec.stream.feed(_ev(kind, 0.5))
        assert rec.calls == []
        assert not rec.stream.in_gesture

    def test_begin_resets_factor_and_emits_own_delta(self):
        rec = _Recorder()
        rec.stream.feed(_ev(PinchKind.BEGIN, 0.002))
        assert rec.calls == [("begin",), ("update", 1.0 * (1.0 + 0.002))]
        assert rec.stream.in_gesture

    def test_end_applies_final_delta_before_on_end(self):
        rec = _Recorder()
        rec.stream.feed(_ev(PinchKind.BEGIN, 0.0))
        rec.stream.feed(_ev(PinchKind.END, 0.5))
        assert rec.calls == [("begin",), ("update", 1.0),
                             ("update", 1.5), ("end", False)]
        assert not rec.stream.in_gesture

    def test_cancel_ends_true_and_drops_its_delta(self):
        """Conservative cancel: the terminating event's value is NEVER
        applied - an unknown-phase event's delta is unvetted evidence, so
        the factor freezes at the last known-good update."""
        rec = _Recorder()
        rec.stream.feed(_ev(PinchKind.BEGIN, 0.0))
        rec.stream.feed(_ev(PinchKind.DELTA, 0.1))
        rec.stream.feed(_ev(PinchKind.CANCEL, 9.9))
        assert rec.calls == [("begin",), ("update", 1.0),
                             ("update", 1.0 * (1.0 + 0.1)), ("end", True)]
        assert not rec.stream.in_gesture

    def test_delta_stream_is_multiplicative(self):
        rec = _Recorder()
        rec.stream.feed(_ev(PinchKind.BEGIN, 0.0))
        rec.stream.feed(_ev(PinchKind.DELTA, 0.5))
        rec.stream.feed(_ev(PinchKind.DELTA, -0.5))
        # (1+0.5)*(1-0.5) = 0.75: absolute factor, not additive drift.
        assert rec.updates == [1.0, 1.5, 1.5 * 0.5]

    def test_cumulative_differencing(self):
        rec = _Recorder()
        rec.stream.feed(_ev(PinchKind.BEGIN, 0.1, cumulative=True))
        rec.stream.feed(_ev(PinchKind.DELTA, 0.3, cumulative=True))
        rec.stream.feed(_ev(PinchKind.END, 0.4, cumulative=True))
        expected_1 = 1.0 * (1.0 + 0.1)
        expected_2 = expected_1 * (1.0 + (0.3 - 0.1))
        expected_3 = expected_2 * (1.0 + (0.4 - 0.3))
        assert rec.updates == [expected_1, expected_2, expected_3]
        assert rec.calls[-1] == ("end", False)

    def test_cumulative_baseline_resets_at_begin(self):
        """A second type-30 gesture must difference against 0.0 again, not
        the previous gesture's final cumulative."""
        rec = _Recorder()
        rec.stream.feed(_ev(PinchKind.BEGIN, 0.2, cumulative=True))
        rec.stream.feed(_ev(PinchKind.END, 0.4, cumulative=True))
        rec.calls.clear()
        rec.stream.feed(_ev(PinchKind.BEGIN, 0.05, cumulative=True))
        # Without the reset the first delta would be 0.05 - 0.4 = -0.35.
        assert rec.calls == [("begin",), ("update", 1.0 * (1.0 + 0.05))]

    def test_begin_while_open_restarts_the_stream(self):
        """Lost end + new physical gesture: the stream simply restarts at
        1.0 (fresh begin, fresh cumulative baseline). The rebase policy for
        the previous gesture lives in the coordinator/machine, not here."""
        rec = _Recorder()
        rec.stream.feed(_ev(PinchKind.BEGIN, 0.0))
        rec.stream.feed(_ev(PinchKind.DELTA, 0.5))
        rec.stream.feed(_ev(PinchKind.BEGIN, 0.002))
        assert rec.calls[-2:] == [("begin",),
                                  ("update", 1.0 * (1.0 + 0.002))]
        assert rec.stream.in_gesture


# ══ Tap-lifecycle section ════════════════════════════════════════════════════
#
# MacOSPinchTranslator is Quartz-lifecycle glue: it owns the CGEventTap and
# routes decoded events into the coordinator's callbacks (the pure decoder +
# stream above do the interpretation). Every test below MOCKS the Quartz
# module surface (injected into sys.modules BEFORE start() imports it), so a
# real CGEventTap is NEVER created under pytest - that would touch the live
# session and can pop a TCC prompt. The mocked module surface also means these
# tests are platform-agnostic: they pin darwin wire semantics but need no real
# darwin (they pass on the Linux CI runner too).


class _FakeQuartz:
    """Stand-in for the Quartz module the tap glue imports at call time.

    Records every call the glue makes (so the lifecycle tests can pin exact
    args) and lets the field getters read the fixture's ``fields`` dict - the
    same object handed in as the opaque CGEvent - by field number. Constant
    IDENTITY is all the glue needs; the disable sentinels use the real
    kCGEventTapDisabledBy* uint32 values so the reason branch is exercised."""

    kCGSessionEventTap = "kCGSessionEventTap"
    kCGHeadInsertEventTap = "kCGHeadInsertEventTap"
    kCGEventTapOptionListenOnly = "kCGEventTapOptionListenOnly"
    kCFRunLoopCommonModes = "kCFRunLoopCommonModes"
    kCGEventTapDisabledByTimeout = 0xFFFFFFFE
    kCGEventTapDisabledByUserInput = 0xFFFFFFFF

    def __init__(self, tap="TAP", source="SOURCE"):
        self._tap_result = tap
        self._source = source
        self.create_args = None
        self.runloop_source_args = None
        self.add_source_args = None
        self.remove_source_args = None
        self.enable_calls = []   # (tap, bool) in call order

    # Tap construction -----------------------------------------------------
    def CGEventTapCreate(self, location, place, options, mask, callback,
                         refcon):
        self.create_args = (location, place, options, mask, callback, refcon)
        return self._tap_result

    def CFMachPortCreateRunLoopSource(self, allocator, tap, order):
        self.runloop_source_args = (allocator, tap, order)
        return self._source

    def CFRunLoopGetMain(self):
        return "MAIN"

    def CFRunLoopAddSource(self, runloop, source, mode):
        self.add_source_args = (runloop, source, mode)

    def CFRunLoopRemoveSource(self, runloop, source, mode):
        self.remove_source_args = (runloop, source, mode)

    def CGEventTapEnable(self, tap, enable):
        self.enable_calls.append((tap, enable))

    # Per-event field reads (the "event" is the fixture fields dict) --------
    def CGEventGetIntegerValueField(self, event, field):
        return int(event.get(field, 0))

    def CGEventGetDoubleValueField(self, event, field):
        return float(event.get(field, 0.0))


def _install_quartz(monkeypatch, tap="TAP"):
    """Route the glue's deferred ``import Quartz`` to a fake. Because the name
    is already in sys.modules, the import short-circuits to the fake on ANY
    platform (no real Quartz needed)."""
    fake = _FakeQuartz(tap=tap)
    monkeypatch.setitem(sys.modules, "Quartz", fake)
    return fake


def _capture_traces(monkeypatch):
    """Redirect overlay_trace to a list so the re-enable / error stamps are
    assertable without relying on TTMT_OVERLAY_TRACE + stderr."""
    traces = []
    monkeypatch.setattr(macos_pinch, "overlay_trace",
                        lambda msg: traces.append(msg))
    return traces


class _TranslatorRecorder:
    """Mimics the coordinator: assigns on_begin / on_update / on_end AFTER
    construction (the translator is zero-arg and late-binds them)."""

    def __init__(self, translator):
        self.calls = []
        translator.on_begin = lambda: self.calls.append(("begin",))
        translator.on_update = lambda f: self.calls.append(("update", f))
        translator.on_end = lambda c: self.calls.append(("end", c))

    @property
    def updates(self):
        return [c[1] for c in self.calls if c[0] == "update"]


def _begin_event(delta=0.01):
    """A minimal cgType-29 zoom BEGIN event (opaque CGEvent == fields dict)."""
    return {FIELD_SUBTYPE: SUBTYPE_ZOOM, FIELD_DELTA: delta,
            FIELD_PHASE: PHASE_BEGAN}


# ── Construction contract ────────────────────────────────────────────────────

class TestTranslatorContract:
    def test_zero_arg_constructible(self):
        MacOSPinchTranslator()   # coordinator builds it with no args

    def test_mechanism_is_cgtap(self):
        # The armed stamp reads this ("[PinchZoom] armed (cgtap) ...").
        assert MacOSPinchTranslator.mechanism == "cgtap"
        assert MacOSPinchTranslator().mechanism == "cgtap"


# ── start(): tap creation arguments ──────────────────────────────────────────

class TestStartCreatesTap:
    def test_create_uses_exact_documented_arguments(self, monkeypatch):
        fake = _install_quartz(monkeypatch)
        _capture_traces(monkeypatch)
        t = MacOSPinchTranslator()
        t.start(())
        location, place, options, mask, callback, refcon = fake.create_args
        assert location == fake.kCGSessionEventTap
        assert place == fake.kCGHeadInsertEventTap
        assert options == fake.kCGEventTapOptionListenOnly
        # Gesture-family (29) + magnify (30): the only two cgTypes decoded.
        assert mask == (1 << 29) | (1 << 30)
        assert callback is t._callback and callable(callback)
        assert refcon is None

    def test_runloop_wiring_and_initial_enable(self, monkeypatch):
        fake = _install_quartz(monkeypatch)
        _capture_traces(monkeypatch)
        t = MacOSPinchTranslator()
        t.start(())
        # CFMachPortCreateRunLoopSource(None, tap, 0)
        assert fake.runloop_source_args == (None, "TAP", 0)
        # CFRunLoopAddSource(main, source, common)
        assert fake.add_source_args == ("MAIN", "SOURCE",
                                        fake.kCFRunLoopCommonModes)
        # CGEventTapEnable(tap, True) exactly once at start.
        assert fake.enable_calls == [("TAP", True)]

    def test_surfaces_are_accepted_and_ignored(self, monkeypatch):
        """The tap is session-wide (it must see pinches while a game/Finder
        is frontmost); the coordinator's cursor gate does all scoping, so
        surfaces are accepted for API parity and dropped."""
        fake = _install_quartz(monkeypatch)
        _capture_traces(monkeypatch)
        t = MacOSPinchTranslator()
        t.start(("cluster", "radial", "panel"))
        # Nothing surface-derived reaches Quartz: one session tap, period.
        assert fake.create_args[0] == fake.kCGSessionEventTap
        assert fake.enable_calls == [("TAP", True)]


# ── start(): denial + protocol misuse ────────────────────────────────────────

class TestStartFailureModes:
    def test_tcc_denial_raises_descriptive_error(self, monkeypatch):
        """CGEventTapCreate returning None == the OS refused the tap (no
        input-monitoring TCC grant / sandbox). start() must raise so the
        coordinator disarms with that cause in the stamp."""
        _install_quartz(monkeypatch, tap=None)
        _capture_traces(monkeypatch)
        t = MacOSPinchTranslator()
        with pytest.raises(RuntimeError,
                           match="input monitoring permission"):
            t.start(())
        # A denied start leaves the object re-armable (no stuck refs).
        assert t._tap is None

    def test_double_start_raises(self, monkeypatch):
        """Two starts without an intervening stop() is protocol misuse - the
        coordinator always stop()s first."""
        _install_quartz(monkeypatch)
        _capture_traces(monkeypatch)
        t = MacOSPinchTranslator()
        t.start(())
        with pytest.raises(RuntimeError):
            t.start(())

    def test_restart_after_stop_creates_a_fresh_tap(self, monkeypatch):
        fake = _install_quartz(monkeypatch)
        _capture_traces(monkeypatch)
        t = MacOSPinchTranslator()
        t.start(())
        t.stop()
        t.start(())   # re-arm path: must not raise
        assert t._tap == "TAP"


# ── stop(): teardown + idempotence ───────────────────────────────────────────

class TestStopTeardown:
    def test_stop_disables_and_removes_source_and_drops_refs(self,
                                                             monkeypatch):
        fake = _install_quartz(monkeypatch)
        _capture_traces(monkeypatch)
        t = MacOSPinchTranslator()
        t.start(())
        t.stop()
        assert fake.enable_calls == [("TAP", True), ("TAP", False)]
        assert fake.remove_source_args == ("MAIN", "SOURCE",
                                           fake.kCFRunLoopCommonModes)
        assert t._tap is None and t._source is None
        assert t._callback is None and t._stream is None

    def test_stop_is_idempotent(self, monkeypatch):
        fake = _install_quartz(monkeypatch)
        _capture_traces(monkeypatch)
        t = MacOSPinchTranslator()
        t.start(())
        t.stop()
        fake.remove_source_args = None   # sentinel: a 2nd remove would reset it
        t.stop()   # safe twice: no Quartz calls, no raise
        assert fake.remove_source_args is None
        assert fake.enable_calls == [("TAP", True), ("TAP", False)]

    def test_stop_before_start_is_safe(self, monkeypatch):
        _install_quartz(monkeypatch)
        _capture_traces(monkeypatch)
        t = MacOSPinchTranslator()
        t.stop()   # never started: no-op, no raise


# ── callback: end-to-end decode through the mocked field getters ─────────────

class TestCallbackRouting:
    def _start(self, monkeypatch, tap="TAP"):
        fake = _install_quartz(monkeypatch, tap=tap)
        traces = _capture_traces(monkeypatch)
        t = MacOSPinchTranslator()
        rec = _TranslatorRecorder(t)
        t.start(())
        return t, fake, traces, rec

    def _replay(self, translator, events):
        """Push (cgType, fields) records through the tap callback exactly as
        the CFRunLoop would (etype == cgType; the fields dict is the opaque
        CGEvent the mocked getters read)."""
        for cgtype, fields in events:
            ret = translator._on_tap_event(None, cgtype, fields, None)
            assert ret is fields   # listen-only: event returned UNCHANGED

    def test_positive_fixture_end_to_end_matches_golden(self, monkeypatch):
        """The real CP-P1 positive gesture, replayed through the tap glue and
        the mocked field getters, must reproduce the decoder-suite's golden
        factor trail bit-for-bit (same deltas, same product order)."""
        _, events = _load("cp_p1_positive_zoom.json")
        deltas = _zoom_deltas(events)              # independent of the glue
        golden = _product_factor(deltas)
        running = []
        factor = 1.0
        for d in deltas:
            factor *= (1.0 + d)
            running.append(factor)

        t, fake, traces, rec = self._start(monkeypatch)
        self._replay(t, events)

        assert rec.calls[0] == ("begin",)
        assert rec.calls[-1] == ("end", False)
        assert rec.updates == running
        assert rec.updates[-1] == golden
        assert golden > 1.0
        # Listen-only never toggles the tap during delivery.
        assert fake.enable_calls == [("TAP", True)]

    def test_type30_fixture_end_to_end_differences_cumulative(self,
                                                              monkeypatch):
        """The cgType-30 path reads d124 (cumulative) and the stream
        differences it - proves the glue selects field 124 by cgType."""
        _, events = _load("cp_p1_type30_cumulative.json")
        cumulatives = [f[FIELD_CUMULATIVE] for typ, f in events
                       if typ == CG_TYPE_MAGNIFY]
        golden, prev = 1.0, 0.0
        for c in cumulatives:
            golden *= (1.0 + (c - prev))
            prev = c
        t, fake, traces, rec = self._start(monkeypatch)
        self._replay(t, events)
        assert rec.calls[0] == ("begin",)
        assert rec.calls[-1] == ("end", False)
        assert rec.updates[-1] == golden

    def test_noise_fixture_produces_no_callbacks(self, monkeypatch):
        _, events = _load("cp_p1_noise_subtypes.json")
        t, fake, traces, rec = self._start(monkeypatch)
        self._replay(t, events)
        assert rec.calls == []


# ── callback: auto-disable re-enable + trace ─────────────────────────────────

class TestDisableReenable:
    def _start(self, monkeypatch):
        fake = _install_quartz(monkeypatch)
        traces = _capture_traces(monkeypatch)
        t = MacOSPinchTranslator()
        _TranslatorRecorder(t)
        t.start(())
        return t, fake, traces

    def test_disable_by_timeout_reenables_and_traces_once(self, monkeypatch):
        t, fake, traces = self._start(monkeypatch)
        sentinel = object()
        ret = t._on_tap_event(None, fake.kCGEventTapDisabledByTimeout,
                              sentinel, None)
        assert ret is sentinel   # the disable event is returned untouched
        # start()'s enable + this re-enable.
        assert fake.enable_calls == [("TAP", True), ("TAP", True)]
        assert traces == ["[PinchZoom] cgtap re-enabled (timeout)"]

    def test_disable_by_user_input_names_that_reason(self, monkeypatch):
        t, fake, traces = self._start(monkeypatch)
        t._on_tap_event(None, fake.kCGEventTapDisabledByUserInput, None, None)
        assert traces == ["[PinchZoom] cgtap re-enabled (userinput)"]

    def test_trace_is_once_per_burst_not_per_event(self, monkeypatch):
        t, fake, traces = self._start(monkeypatch)
        # A storm of back-to-back disables re-enables every time but traces
        # only on the leading edge.
        for _ in range(4):
            t._on_tap_event(None, fake.kCGEventTapDisabledByTimeout, None,
                            None)
        assert traces == ["[PinchZoom] cgtap re-enabled (timeout)"]
        assert fake.enable_calls == [("TAP", True)] + [("TAP", True)] * 4
        # A real event flows: the burst is over, the next disable traces anew.
        t._on_tap_event(None, CG_TYPE_GESTURE, _begin_event(), None)
        t._on_tap_event(None, fake.kCGEventTapDisabledByTimeout, None, None)
        assert traces == ["[PinchZoom] cgtap re-enabled (timeout)",
                          "[PinchZoom] cgtap re-enabled (timeout)"]


# ── callback: exceptions never escape the CFRunLoop ──────────────────────────

class TestCallbackExceptionTrapped:
    def test_callback_error_is_trapped_and_later_events_still_flow(
            self, monkeypatch):
        """A decode/callback fault must not escape into the run loop (it would
        kill event delivery process-wide). The tap stays enabled, the fault
        traces once, and subsequent events still reach the decoder."""
        fake = _install_quartz(monkeypatch)
        traces = _capture_traces(monkeypatch)
        t = MacOSPinchTranslator()

        seen = {"begins": 0}
        boom = {"fired": False}

        def on_begin():
            if not boom["fired"]:
                boom["fired"] = True
                raise RuntimeError("decode boom")
            seen["begins"] += 1

        t.on_begin = on_begin
        t.on_update = lambda f: None
        t.on_end = lambda c: None
        t.start(())

        # First BEGIN -> on_begin raises -> trapped (no exception escapes).
        ret = t._on_tap_event(None, CG_TYPE_GESTURE, _begin_event(0.01), None)
        assert ret is not None            # returned the event, did not raise
        assert seen["begins"] == 0
        # Second BEGIN -> flows through cleanly: later events still deliver.
        t._on_tap_event(None, CG_TYPE_GESTURE, _begin_event(0.02), None)
        assert seen["begins"] == 1
        # The tap was NEVER disabled by the fault (delivery survives).
        assert ("TAP", False) not in fake.enable_calls
        # Traced once, not per faulting event.
        assert traces == [t_ for t_ in traces if "callback error" in t_]
        assert sum("callback error" in m for m in traces) == 1
