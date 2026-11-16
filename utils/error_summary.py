"""Pill-sized summaries of launch and sign-in errors, for launcher cards.

Moved from utils/widgets/account_tile.py (the legacy launcher tile) so the
Grandstand roster card keeps it after the legacy launcher is removed."""
from __future__ import annotations


def summarize_error(raw_message: str) -> str:
    """Curate a pill-sized summary from a raw error string.
    Pure function so it's straightforward to test."""
    if not raw_message:
        return "Failed"
    lower = raw_message.lower()
    if "401" in lower or "bad creds" in lower or "incorrect username or password" in lower:
        return "Bad credentials"
    if "queue" in lower and ("timeout" in lower or "timed out" in lower):
        return "Queue timed out"
    if "network" in lower or "connection" in lower or "timeout" in lower:
        return "Network error"
    if "engine not found" in lower or "ttrengine" in lower:
        return "Engine not found"
    if "not installed" in lower:
        return "Runtime missing"
    if "wine" in lower or "proton" in lower or "umu" in lower:
        return "Runtime error"
    # Default: truncate to ~32 chars.
    return (raw_message[:32] + "…") if len(raw_message) > 32 else raw_message
