"""Shared user-facing copy for credential storage conditions."""
from dataclasses import dataclass


@dataclass(frozen=True)
class CredentialCopy:
    """One credential condition's wording and optional recovery action."""

    header: str
    body: str
    action_text: str = ""

    def hero_reason(self) -> str:
        return f"{self.header}\n{self.body}"

    def advisory_reason(self) -> str:
        return " ".join(self.body.splitlines())


KEYRING_WARNING_COPY = CredentialCopy(
    header="⚠  Credential Storage Unavailable",
    body=(
        "No system wallet service was detected. Your account usernames are saved,\n"
        "but passwords will not be remembered between sessions - you'll need to\n"
        "re-enter them each time you launch TTMT."
    ),
)

MACOS_VAULT_COPY = {
    "denied": CredentialCopy(
        header="🔒  Your accounts are locked",
        body="Unlock to load your saved accounts for this session.",
        action_text="Unlock accounts",
    ),
    "corrupt": CredentialCopy(
        header="⚠  Couldn't open your saved accounts",
        body=(
            "Your saved accounts could not be unlocked, so they are not\n"
            "available this session. Your data was left untouched. Restart\n"
            "TTMT to try again; if it keeps happening, please share the\n"
            "keyring-debug.log file when reporting."
        ),
    ),
}
