"""Log line records + classification. Pure Python (datetime + re only) so
the classifier and routing rules are unit-testable without Qt.

Source routing is a VERBATIM port of the old DebugTab.append_log containment
rules — parity is pinned by tests; do not "improve" it to prefix matching."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

INPUT_TAGS = ("[Input]", "[KeepAlive]", "[Hotkey]", "[Service]")
API_TAGS = ("[TTR API]", "[Profile]", "[Launch]")
LEVELS = ("info", "ok", "warn", "error")

_LEADING_TAG = re.compile(r"^(\[[^\[\]]+\])\s*")
# Spec keyword sets. Word-boundaried alternatives, including the multi-word
# phrases (spaces are fine between \b anchors).
_ERROR_RE = re.compile(
    r"\b(error|failed|failure|exception|traceback|denied|cannot|unable)\b"
    r"|\bcould not\b", re.IGNORECASE)
_WARN_RE = re.compile(
    r"\b(warning|unavailable|fallback|retrying|retry|slow|skipped|missing"
    r"|deprecated)\b|\bfalling back\b", re.IGNORECASE)
_OK_RE = re.compile(
    r"\b(ok|success|succeeded|detected|issued|verified|ready|connected)\b",
    re.IGNORECASE)


@dataclass(frozen=True)
class LogLine:
    time: datetime
    source: str    # raw | input | api
    tag: str       # "[Credentials]" form, or "" when untagged
    level: str     # info | ok | warn | error
    message: str   # tag-stripped remainder


def classify_source(message: str) -> str:
    if any(t in message for t in INPUT_TAGS):
        return "input"
    if any(t in message for t in API_TAGS):
        return "api"
    return "raw"


def split_leading_tag(message: str) -> tuple[str, str]:
    m = _LEADING_TAG.match(message)
    if m:
        return m.group(1), message[m.end():]
    return "", message


def classify_level(message: str) -> str:
    """Keyword-based and negation-blind ("Server not connected" classifies
    ok); callers pass an explicit level for negated/ambiguous states."""
    if _ERROR_RE.search(message):
        return "error"
    if _WARN_RE.search(message):
        return "warn"
    if _OK_RE.search(message):
        return "ok"
    return "info"


def make_line(message: str, level: str | None = None,
              now: datetime | None = None) -> LogLine:
    tag, rest = split_leading_tag(message)
    return LogLine(
        time=now or datetime.now(),
        source=classify_source(message),
        tag=tag,
        level=level if level in LEVELS else classify_level(message),
        message=rest,
    )


def format_line(line: LogLine) -> str:
    """Copy/export format: `[HH:MM:SS] [Tag] message`."""
    ts = line.time.strftime("%H:%M:%S")
    tag = f"{line.tag} " if line.tag else ""
    return f"[{ts}] {tag}{line.message}"
