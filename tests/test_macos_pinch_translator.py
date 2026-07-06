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
