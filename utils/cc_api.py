"""Corporate Clash data layer -- parses CC's captured stdout for toon info.

Replaces the previous stub. The stub's `get_toon_names_threaded(num_slots,
callback, current_window_ids)` signature is kept as a thin compatibility
shim that delegates to the new richer API; callers can migrate at their
own pace.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable, Optional

from services import cc_launcher
from utils import cc_species, cc_stdout_parser, cc_zones
from utils.cc_toon_info import CCToonInfo


logger = logging.getLogger(__name__)


# -- Public API ----------------------------------------------------------------


def get_toon_data_threaded(
    num_slots: int,
    window_ids: list,
    callback: Callable[[list[Optional[CCToonInfo]]], None],
) -> None:
    """Fetch CC toon data for the given windows, fire callback with a
    list[CCToonInfo | None] padded to num_slots.

    Threaded so the parser file-I/O doesn't block the GUI. The callback
    is invoked on the worker thread; Qt callers should wrap it with a
    Signal.emit to marshal back to the GUI thread.
    """
    def _worker():
        try:
            infos: list[Optional[CCToonInfo]] = []
            for wid in window_ids:
                info = _resolve_one(wid)
                infos.append(info)
            # Pad out to num_slots so the callback always sees a fixed-
            # length list. Matches the TTR API's behavior.
            while len(infos) < num_slots:
                infos.append(None)
            callback(infos)
        except Exception:
            logger.exception("[cc_api] worker crashed; firing empty callback")
            callback([None] * num_slots)

    threading.Thread(target=_worker, daemon=True).start()


def get_toon_names_threaded(num_slots: int, callback, current_window_ids=None) -> None:
    """Compatibility shim for legacy callers.

    The old stub's callback signature was
        callback(names, styles, colors, laffs, max_laffs, beans)
    with all-None. This shim preserves that exactly: every list is
    [None] * num_slots. New code should call `get_toon_data_threaded`
    directly.
    """
    names = [None] * num_slots
    styles = [None] * num_slots
    colors = [None] * num_slots
    laffs = [None] * num_slots
    max_laffs = [None] * num_slots
    beans = [None] * num_slots
    callback(names, styles, colors, laffs, max_laffs, beans)


# -- Internals (replaceable in tests) -----------------------------------------


def _resolve_pid_for_window(window_id) -> Optional[int]:
    """Return the OS PID for a given window ID, or None if unresolvable.

    Linux: uses x11_discovery.get_window_pid.
    Windows: uses win32 GetWindowThreadProcessId.
    """
    import sys
    try:
        if sys.platform == "win32":
            import win32process
            _tid, pid = win32process.GetWindowThreadProcessId(int(window_id))
            return pid or None
        else:
            from utils import x11_discovery
            return x11_discovery.get_window_pid(window_id)
    except Exception:
        logger.exception("[cc_api] _resolve_pid_for_window failed for %r", window_id)
        return None


def _get_stdout_path_for_pid(pid: int) -> Optional[Path]:
    """Indirection over cc_launcher.get_stdout_path_for_pid for test mocking."""
    return cc_launcher.get_stdout_path_for_pid(pid)


def _resolve_one(window_id) -> CCToonInfo:
    """Build a CCToonInfo for one window. Returns an all-None info when
    any step degrades (no PID, no stdout file, no avatar record yet)."""
    pid = _resolve_pid_for_window(window_id)
    if pid is None:
        return CCToonInfo()

    path = _get_stdout_path_for_pid(pid)
    if path is None:
        return CCToonInfo()

    try:
        text = path.read_text(errors="replace")
    except OSError:
        logger.exception("[cc_api] failed to read CC stdout %s", path)
        return CCToonInfo()

    avatar = cc_stdout_parser.parse_avatar_record(text)
    if avatar is None:
        # Window exists, log file exists, but user hasn't picked an
        # avatar yet. Wait for next poll.
        return CCToonInfo()

    species_letter = avatar.head_code[0] if avatar.head_code else None
    species_name, species_emoji = (None, "❓")
    if species_letter:
        species_name, species_emoji = cc_species.lookup(species_letter)

    zone = cc_stdout_parser.parse_latest_zone(text, av_id=avatar.doid)
    playground, zone_name = (None, None)
    if zone is not None:
        playground, zone_name = cc_zones.lookup(zone.zone_id, zone.hood_id)

    return CCToonInfo(
        name=avatar.name,
        head_code=avatar.head_code,
        species_letter=species_letter,
        species_name=species_name,
        species_emoji=species_emoji,
        playground=playground,
        zone_name=zone_name,
        dna_colors=avatar.dna_colors,
    )
