"""Guard: every GitHub Actions workflow commits as the human maintainer.

A workflow that runs `git config user.name/user.email` with a bot identity
(e.g. github-actions[bot]) and then commits adds that bot to the repo's
Contributors list. Project law: contributors are humans only. This test scans
every workflow's git-identity settings and fails on anything that is not the
maintainer. Pure file scan - no Qt, runs in the CI self-check or anywhere.
"""
import pathlib
import re

MAINTAINER_NAME = "flossbud"
MAINTAINER_EMAIL = "flossbud27@gmail.com"

WORKFLOWS = pathlib.Path(__file__).resolve().parents[1] / ".github" / "workflows"

_IDENTITY_RE = re.compile(r"git\s+config\s+user\.(name|email)\s+(.+)")


def _workflow_git_identities():
    """[(filename, lineno, 'name'|'email', value), ...] for every git-identity
    line set in any workflow, quotes stripped."""
    hits = []
    for wf in sorted(WORKFLOWS.glob("*.yml")):
        for lineno, line in enumerate(wf.read_text().splitlines(), 1):
            m = _IDENTITY_RE.search(line.strip())
            if m:
                key, raw = m.group(1), m.group(2).strip()
                value = raw.strip('"').strip("'")
                hits.append((wf.name, lineno, key, value))
    return hits


def test_workflows_commit_only_as_the_maintainer():
    expected = {"name": MAINTAINER_NAME, "email": MAINTAINER_EMAIL}
    offenders = [
        (f, ln, k, v) for (f, ln, k, v) in _workflow_git_identities()
        if v != expected[k]
    ]
    assert not offenders, (
        "Workflows must commit as the maintainer, not a bot:\n"
        + "\n".join(f"  {f}:{ln}  user.{k} = {v!r}" for (f, ln, k, v) in offenders)
    )
