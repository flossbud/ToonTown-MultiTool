"""Windows integrity-level capability detection for synthetic-input delivery.

PostMessage to a higher-integrity window is silently dropped by UIPI (the call
still reports success). We therefore decide BEFORE sending whether a window is
reachable by comparing token integrity levels. Off Windows this whole module is
a no-op: capability checks resolve to OK so callers behave exactly as before.
"""
from __future__ import annotations

import enum
import sys


class Capability(enum.Enum):
    OK = "ok"                    # target integrity <= ours: deliverable
    BLOCKED_UIPI = "blocked"     # target integrity > ours: PostMessage silently dropped
    UNKNOWN = "unknown"          # could not determine; treat as unsafe for suppression


def classify_integrity(own_il, target_il) -> Capability:
    """Pure classifier. own_il/target_il are integrity RIDs (ints) or None.

    TTMT official builds are never uiAccess (unsigned, per-user, asInvoker), so
    own uiAccess is treated as always False; the uiAccess-bypass case is
    unreachable and needs no branch beyond that.
    """
    if own_il is None or target_il is None:
        return Capability.UNKNOWN
    if target_il > own_il:
        return Capability.BLOCKED_UIPI
    return Capability.OK
