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

---

### Bug Fixes

- Fixed the app freezing briefly when you switched focus to another window.
- Fixed multiple windows of the app appearing as separate entries in the taskbar.
- Fixed the status dot and Default button colors not updating with the active theme.
- Fixed visible artifacts in the corners of account cards.
- Fixed brief flicker when resizing between Compact and Full Multitoon layouts.
- Fixed Keep-Alive widgets being misaligned in the chat-only Compact view.
- Fixed buttons and portraits staying small after switching from Full UI back to Compact.
- Removed a harmless warning that printed during launch.
- Windows: the app launches significantly faster.
- Windows: the app icon now shows correctly in the taskbar and title bar while the app is running.
- Windows: the app icon now shows on the EXE in Explorer.
- Windows: removed a brief console flash that appeared when detecting game windows.
- Windows: fixed the app being blocked by Smart App Control on launch.

---

### Downloads

| File | Platform |
|------|----------|
| `ToonTownMultiTool-v2.1.0-Windows-x86_64.zip` | Windows 10/11 |
| `TTMultiTool-v2.1.0-Linux-x86_64.AppImage` | Linux (X11 / Wayland) |
| `TTMultiTool-v2.1.0-Linux-x86_64.flatpak` | Linux Flatpak |

> Windows: extract the zip anywhere and run `ToonTownMultiTool.exe` from inside the extracted folder.

---

### Running from Source

```bash
git clone https://github.com/flossbud/ToonTown-MultiTool.git
cd ToonTown-MultiTool
pip install -r requirements.txt
python main.py
```
