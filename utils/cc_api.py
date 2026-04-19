"""
Corporate Clash local API — permanent stub.

Corporate Clash does not expose a local HTTP companion API like TTR does on
ports 1547-1552. CC only has Discord Rich Presence IPC, which does not provide
toon name, laff, or bean data for polling.

This stub exists so the multitoon tab can call cc_api.get_toon_names_threaded()
the same way it calls ttr_api.get_toon_names_threaded(), keeping the dispatch
path symmetric. It returns all-None data synchronously with zero overhead.

If CC ships a companion API in the future, this file is replaced with a real
implementation — no changes needed elsewhere.
"""


def get_toon_names_threaded(num_slots: int, callback, current_window_ids: list = None) -> None:
    """Return None for all toon data fields immediately (no thread needed)."""
    names     = [None] * num_slots
    styles    = [None] * num_slots
    colors    = [None] * num_slots
    laffs     = [None] * num_slots
    max_laffs = [None] * num_slots
    beans     = [None] * num_slots
    callback(names, styles, colors, laffs, max_laffs, beans)
