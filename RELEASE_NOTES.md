## ToonTown MultiTool v2.0.3

Patch release fixing credential storage on KDE Plasma.

---

### Bug Fixes

- Fixed AppImage builds being unable to read passwords stored in KDE Wallet, which caused accounts to fail to launch with no error message after a system reboot.

### Improvements

- Added a portable, pure-Python KWallet backend so packaged builds work on KDE without needing system Python bindings installed.

---

### Downloads

| File | Platform |
|------|----------|
| `ToonTownMultiTool-v2.0.3-Windows-x86_64.exe` | Windows 10/11 |
| `TTMultiTool-v2.0.3-Linux-x86_64.AppImage` | Linux (X11 / Wayland) |

---

### Running from Source

```bash
git clone https://github.com/flossbud/ToonTown-MultiTool.git
cd ToonTown-MultiTool
pip install -r requirements.txt
python main.py
```
