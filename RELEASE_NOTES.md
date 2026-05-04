## ToonTown MultiTool v2.1.0

Major release adding opt-in Keep-Alive with TOS consent and a redesigned Multitoon Full UI.

---

### Improvements

- New Keep-Alive opt-in system: master toggle in Settings gated behind a TOS-aware consent dialog, with per-toon selections preserved across master toggles.
- Redesigned Multitoon Full UI: new aspect-ratio cards (7:4, max 1050px), centered control block, proportional content scaling, status indicator with pulse animation.
- Cross-fade animation when Multitoon swaps between Compact and Full UI layouts.
- Keep-Alive widget visibility now animates: opacity fade in Full UI, frame expand/collapse in Compact.
- New theme palettes: cool slate light theme and charcoal-saturated dark theme, with AA-compliant accent button text.
- Subtle vertical gradient on the light-mode app background.
- Wider default window (575px min width, 740px default height) to fit redesigned content.
- Non-Multitoon tabs are now clamped and centered at 720px max width for better readability on wide windows.
- Typography scale (`font_role`) added and migrated into the header.

---

### Bug Fixes

- Fixed hotkey listener blocking the GUI on focus loss by joining the pynput listener off-thread.
- Fixed launch-animation `RuntimeWarning` caused by a dead signal disconnect.
- Fixed taskbar grouping by setting a stable Qt application identity.
- Fixed status dot and Default button off-states to follow the active theme.
- Fixed account-card outer frame transparency so corner wedges no longer show through.
- Fixed cross-fade race where `layout_mode` was committed asynchronously.
- Fixed Keep-Alive ka_group horizontal margins in chat-only Compact frame.
- Fixed Full UI button and portrait sizing not resetting after a Full to Compact roundtrip.
- Windows: embedded the app icon in the PyInstaller `.exe`.
- Windows: suppressed console flash when probing the TTR API port.

---

### Downloads

| File | Platform |
|------|----------|
| `ToonTownMultiTool-v2.1.0-Windows-x86_64.exe` | Windows 10/11 |
| `TTMultiTool-v2.1.0-Linux-x86_64.AppImage` | Linux (X11 / Wayland) |
| `TTMultiTool-v2.1.0-Linux-x86_64.flatpak` | Linux Flatpak |

---

### Running from Source

```bash
git clone https://github.com/flossbud/ToonTown-MultiTool.git
cd ToonTown-MultiTool
pip install -r requirements.txt
python main.py
```
