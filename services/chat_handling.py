"""Which toons get chat keystrokes broadcast to them.

A pure rule shared by every front end that feeds ``InputService``; the
canonical mode values and their normalizer live in ``utils.settings_keys``.
"""

from __future__ import annotations


def compute_effective_chat_enabled(
    mode: str,
    raw_chat: list[bool],
    enabled_toons: list[bool],
    assignments: list[int],
) -> list[bool]:
    """Compute per-toon effective chat-broadcast state.

    Expects an already-normalized mode (use normalize_chat_handling_mode
    before calling). The four canonical modes behave as follows:

    - per_toon:       returns raw_chat verbatim, length-normalized to
                      len(enabled_toons); downstream InputService callers
                      never read past the end of raw_chat.
    - all_toons:      every enabled toon broadcasts chat (disabled -> False),
                      regardless of keyset assignment or raw_chat.
    - focused_only:   all False; chat is handled by the game's own focused
                      window, not broadcast by TTMT.
    - keyset_dynamic: (default / fallback) each toon is True iff the toon is
                      enabled AND its assigned keyset index is 0. Assignments
                      shorter than enabled_toons treat missing indices as
                      non-default keyset (chat off).

    Result length always equals len(enabled_toons).

    See: docs/superpowers/specs/2026-06-09-chat-handling-logic-dropdown-design.md
    """
    from utils.settings_keys import (
        CHAT_HANDLING_PER_TOON,
        CHAT_HANDLING_ALL_TOONS,
        CHAT_HANDLING_FOCUSED_ONLY,
    )
    n = len(enabled_toons)
    if mode == CHAT_HANDLING_PER_TOON:
        return [bool(raw_chat[i]) if i < len(raw_chat) else False for i in range(n)]
    if mode == CHAT_HANDLING_ALL_TOONS:
        return [bool(enabled_toons[i]) for i in range(n)]
    if mode == CHAT_HANDLING_FOCUSED_ONLY:
        return [False] * n
    return [
        bool(enabled_toons[i]) and i < len(assignments) and assignments[i] == 0
        for i in range(n)
    ]
