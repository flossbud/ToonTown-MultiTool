# utils/cc_api.py

## Purpose

Permanent stub representing the Corporate Clash local companion API. Corporate Clash does not expose a local HTTP API equivalent to TTR's ports 1547–1552. CC only exposes Discord Rich Presence IPC, which does not provide toon name, laff, or bean data in a pollable form.

This stub exists to keep the dispatch path in `MultitoonTab` symmetric: both `ttr_api.get_toon_names_threaded()` and `cc_api.get_toon_names_threaded()` have identical signatures, so no conditional branching is needed in the caller.

---

## Design Decision: Stub over Conditional

Without this stub, `MultitoonTab` would need:

```python
if game == "ttr":
    ttr_api.get_toon_names_threaded(...)
# else: nothing (CC has no API)
```

With the stub:

```python
api_module.get_toon_names_threaded(...)
```

The stub returns all-`None` synchronously and invokes the callback immediately — zero overhead, zero threads created.

---

## Function: `get_toon_names_threaded(num_slots, callback, current_window_ids=None)`

```python
names     = [None] * num_slots
styles    = [None] * num_slots
colors    = [None] * num_slots
laffs     = [None] * num_slots
max_laffs = [None] * num_slots
beans     = [None] * num_slots
callback(names, styles, colors, laffs, max_laffs, beans)
```

No thread is spawned. The callback fires synchronously in the calling thread. The caller (`MultitoonTab`) handles `None` values gracefully — slots show a placeholder portrait and no toon name.

---

## Future Compatibility

The module docstring explicitly states: *"If CC ships a companion API in the future, this file is replaced with a real implementation — no changes needed elsewhere."* The stub makes the upgrade path clean — replace the body of `get_toon_names_threaded()` without touching any caller.

---

## Dependencies

None.
