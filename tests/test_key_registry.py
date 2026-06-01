"""Cross-layer invariant tests for the canonical key registry.

Run with: TTMT_NO_VENV_REEXEC=1 QT_QPA_PLATFORM=offscreen pytest tests/test_key_registry.py -v

Tests 1, 3, 6, 7 pass before any wiring (pure data / existing dicts already match).
Tests 2, 8, 9 pass after Task 3 (input_service.py wired).
Tests 4, 5, 10 pass after Task 5 (keymap_tab.py wired).
"""
from utils.key_registry import NAMED_KEY_REGISTRY, PASSTHROUGH_KEYSYMS


# ── Test 1: structural integrity ───────────────────────────────────────────

def test_no_duplicate_canonicals():
    canonicals = [kd.canonical for kd in NAMED_KEY_REGISTRY]
    dupes = [c for c in canonicals if canonicals.count(c) > 1]
    assert not dupes, f"Duplicate canonicals in registry: {dupes}"


# ── Test 2: send-time resolution ───────────────────────────────────────────

def test_every_canonical_resolves_at_send_time():
    """Every registry canonical must resolve via _resolve_keysym to its
    expected X11 keysym (keysyms[0]) — not just to something non-None.
    Comparing the value catches wiring that resolves to the wrong keysym.
    Fails for Home/End/Prior/Next/Insert until input_service.py is wired
    (Task 3)."""
    from services.input_service import _resolve_keysym
    failures = []
    for kd in NAMED_KEY_REGISTRY:
        result = _resolve_keysym(kd.canonical)
        if result != kd.keysyms[0]:
            failures.append(
                f"_resolve_keysym({kd.canonical!r}) = {result!r}, "
                f"expected {kd.keysyms[0]!r}"
            )
    assert not failures, "\n".join(failures)


# ── Test 3: pynput name coverage ──────────────────────────────────────────

def test_every_pynput_name_maps_to_correct_canonical():
    """Every pynput_name in the registry appears in PYNPUT_NAME_MAP
    and maps to the expected canonical."""
    from services.hotkey_manager import HotkeyManager
    nm = HotkeyManager.PYNPUT_NAME_MAP
    failures = []
    for kd in NAMED_KEY_REGISTRY:
        for name in kd.pynput_names:
            if name not in nm:
                failures.append(f"missing: {name!r} (for {kd.canonical!r})")
            elif nm[name] != kd.canonical:
                failures.append(
                    f"wrong: PYNPUT_NAME_MAP[{name!r}]={nm[name]!r}, "
                    f"expected {kd.canonical!r}"
                )
    assert not failures, "\n".join(failures)


# ── Test 4: UI capture — SPECIAL_KEYS ─────────────────────────────────────

def test_every_special_key_qt_variant_in_special_keys():
    """Every non-modifier, non-numpad entry's qt_key_names all map to
    the correct canonical in SPECIAL_KEYS. Fails for F1-F12 and nav
    cluster until keymap_tab.py is wired (Task 5)."""
    from PySide6.QtCore import Qt
    from tabs.keymap_tab import SPECIAL_KEYS
    failures = []
    for kd in NAMED_KEY_REGISTRY:
        if kd.numpad_key or kd.category == "modifier":
            continue
        for qt_name in kd.qt_key_names:
            qt_val = int(getattr(Qt, qt_name))
            if qt_val not in SPECIAL_KEYS:
                failures.append(
                    f"Qt.{qt_name} missing from SPECIAL_KEYS "
                    f"(canonical: {kd.canonical!r})"
                )
            elif SPECIAL_KEYS[qt_val] != kd.canonical:
                failures.append(
                    f"SPECIAL_KEYS[Qt.{qt_name}]={SPECIAL_KEYS[qt_val]!r}, "
                    f"expected {kd.canonical!r}"
                )
    assert not failures, "\n".join(failures)


# ── Test 5: UI capture — _NUMPAD_KEYS ────────────────────────────────────

def test_every_numpad_qt_variant_in_numpad_keys():
    """Every numpad entry's qt_key_names (both NumLock-on and NumLock-off
    variants) all map to the correct canonical in _NUMPAD_KEYS. Fails for
    KP_5 Key_Clear variant until keymap_tab.py is wired (Task 5)."""
    from PySide6.QtCore import Qt
    from tabs.keymap_tab import MovementKeyField
    nk = MovementKeyField._NUMPAD_KEYS
    failures = []
    for kd in NAMED_KEY_REGISTRY:
        if not kd.numpad_key:
            continue
        for qt_name in kd.qt_key_names:
            qt_val = int(getattr(Qt, qt_name))
            if qt_val not in nk:
                failures.append(
                    f"Qt.{qt_name} ({qt_val}) missing from _NUMPAD_KEYS "
                    f"(canonical: {kd.canonical!r})"
                )
            elif nk[qt_val] != kd.canonical:
                failures.append(
                    f"_NUMPAD_KEYS[Qt.{qt_name}]={nk[qt_val]!r}, "
                    f"expected {kd.canonical!r}"
                )
    assert not failures, "\n".join(failures)


# ── Test 6: pynput VK coverage ────────────────────────────────────────────

def test_numpad_canonicals_covered_in_vk_map():
    """Every numpad canonical appears in PYNPUT_VK_MAP.values()."""
    from services.hotkey_manager import HotkeyManager
    vk_values = set(HotkeyManager.PYNPUT_VK_MAP.values())
    failures = [
        kd.canonical
        for kd in NAMED_KEY_REGISTRY
        if kd.category == "numpad" and kd.canonical not in vk_values
    ]
    assert not failures, (
        f"Numpad canonicals missing from PYNPUT_VK_MAP: {failures}"
    )


# ── Test 7: VK map closure ────────────────────────────────────────────────

def test_no_vk_map_value_missing_from_registry():
    """No PYNPUT_VK_MAP value references a canonical absent from the
    registry. Prevents drift where VK map grows but registry doesn't."""
    from services.hotkey_manager import HotkeyManager
    all_canonicals = {kd.canonical for kd in NAMED_KEY_REGISTRY}
    failures = [
        f"VK {vk} -> {canonical!r}"
        for vk, canonical in HotkeyManager.PYNPUT_VK_MAP.items()
        if canonical not in all_canonicals
    ]
    assert not failures, (
        "PYNPUT_VK_MAP values not in registry:\n" + "\n".join(failures)
    )


# ── Test 8: explicit round-trips ──────────────────────────────────────────

def test_nav_and_function_key_round_trips():
    """Explicit send-time round-trips for previously-broken keys.
    Fails for nav cluster until input_service.py is wired (Task 3)."""
    from services.input_service import _resolve_keysym
    cases = [
        ("Home",    "Home"),
        ("End",     "End"),
        ("Prior",   "Prior"),
        ("Next",    "Next"),
        ("Insert",  "Insert"),
        ("F1",      "F1"),
        ("F12",     "F12"),
        ("KP_0",    "KP_0"),
        ("KP_5",    "KP_5"),
        ("KP_Enter","KP_Enter"),
    ]
    failures = []
    for canonical, expected in cases:
        result = _resolve_keysym(canonical)
        if result != expected:
            failures.append(
                f"_resolve_keysym({canonical!r}) = {result!r}, expected {expected!r}"
            )
    assert not failures, "\n".join(failures)


# ── Test 9: passthrough coverage ──────────────────────────────────────────

def test_passthrough_contains_critical_keys():
    """_passthrough_keysyms_for_canonical must contain EVERY registry
    passthrough keysym, not just a handpicked subset. Asserting the full
    PASSTHROUGH_KEYSYMS set catches wiring that adds only some keys (e.g.
    a few literals) while omitting other registry passthrough entries.
    Fails until input_service.py is wired (Task 3)."""
    from services.input_service import _passthrough_keysyms_for_canonical
    pt = set(_passthrough_keysyms_for_canonical("wasd"))
    missing = set(PASSTHROUGH_KEYSYMS) - pt
    assert not missing, (
        f"Registry passthrough keysyms missing from passthrough tuple: "
        f"{sorted(missing)}"
    )


# ── Test 10: DISPLAY_NAMES wiring ─────────────────────────────────────────

def test_display_names_derived_from_registry():
    """Every registry canonical has a DISPLAY_NAMES entry equal to its
    registry display string. Guards against Task 5 wiring SPECIAL_KEYS /
    _NUMPAD_KEYS but forgetting DISPLAY_NAMES. Fails until keymap_tab.py
    is wired (Task 5) — F-keys and nav cluster are absent from the old
    hardcoded DISPLAY_NAMES."""
    from tabs.keymap_tab import DISPLAY_NAMES
    failures = []
    for kd in NAMED_KEY_REGISTRY:
        if kd.canonical not in DISPLAY_NAMES:
            failures.append(f"missing: {kd.canonical!r}")
        elif DISPLAY_NAMES[kd.canonical] != kd.display:
            failures.append(
                f"wrong: DISPLAY_NAMES[{kd.canonical!r}]="
                f"{DISPLAY_NAMES[kd.canonical]!r}, expected {kd.display!r}"
            )
    assert not failures, "\n".join(failures)
