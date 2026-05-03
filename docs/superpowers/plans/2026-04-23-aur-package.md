# AUR Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish `toontown-multitool` to the AUR so Arch users can install via `yay`/`paru`.

**Architecture:** A PKGBUILD that downloads the GitHub source tarball, installs Python files to `/usr/share/toontown-multitool/`, creates a launcher script + symlink, and installs a `.desktop` file and icon. The PKGBUILD lives in a separate AUR git repo. A system-install `.desktop` file is added to the main project repo.

**Tech Stack:** makepkg, PKGBUILD, AUR git

---

### File Map

| File | Location | Purpose |
|------|----------|---------|
| `toontown-multitool.desktop` | Main repo (new) | Desktop entry for system-wide install |
| `PKGBUILD` | AUR repo (new) | AUR build recipe |
| `.SRCINFO` | AUR repo (generated) | AUR metadata index |

---

### Task 1: Add desktop file to main repo

**Files:**
- Create: `toontown-multitool.desktop`

- [ ] **Step 1: Create the desktop entry file**

Create `toontown-multitool.desktop` in the project root:

```ini
[Desktop Entry]
Name=ToonTown MultiTool
Comment=Multiboxing input control for Toontown
Exec=toontown-multitool
Icon=toontown-multitool
Type=Application
Categories=Game;
```

- [ ] **Step 2: Validate the desktop file**

Run: `desktop-file-validate toontown-multitool.desktop 2>&1 || echo "desktop-file-validate not installed, skipping"`

Expected: No errors (or tool not installed, which is fine)

- [ ] **Step 3: Commit**

```bash
git add toontown-multitool.desktop
git commit -m "chore: add desktop entry for system-wide installs"
```

---

### Task 2: Create the PKGBUILD

This task is done in a **separate directory** outside the main repo since the AUR has its own git repo.

- [ ] **Step 1: Create the AUR repo directory**

```bash
mkdir -p ~/Projects/aur-toontown-multitool
cd ~/Projects/aur-toontown-multitool
git init
```

- [ ] **Step 2: Write the PKGBUILD**

Create `PKGBUILD`:

```bash
# Maintainer: flossbud <flossbud27@gmail.com>
pkgname=toontown-multitool
pkgver=2.0.1
pkgrel=1
pkgdesc="Multiboxing input control for Toontown Rewritten and Corporate Clash"
arch=('any')
url="https://github.com/flossbud/ToonTown-MultiTool"
license=('MIT')
depends=(
    'python'
    'python-pyside6'
    'python-pynput'
    'python-requests'
    'python-keyring'
    'python-certifi'
    'python-cryptography'
    'python-xlib'
    'python-secretstorage'
    'python-jeepney'
    'xdotool'
)
source=("${pkgname}-${pkgver}.tar.gz::https://github.com/flossbud/ToonTown-MultiTool/archive/refs/tags/v${pkgver}.tar.gz")
sha256sums=('SKIP')

package() {
    cd "ToonTown-MultiTool-${pkgver}"

    # Install Python source
    install -dm755 "${pkgdir}/usr/share/${pkgname}"
    cp -r main.py tabs/ utils/ services/ "${pkgdir}/usr/share/${pkgname}/"

    # Install launcher script
    install -dm755 "${pkgdir}/usr/bin"
    cat > "${pkgdir}/usr/bin/${pkgname}" << 'EOF'
#!/bin/bash
exec python /usr/share/toontown-multitool/main.py "$@"
EOF
    chmod 755 "${pkgdir}/usr/bin/${pkgname}"

    # Symlink ttmt -> toontown-multitool
    ln -s "${pkgname}" "${pkgdir}/usr/bin/ttmt"

    # Install desktop entry
    install -Dm644 toontown-multitool.desktop "${pkgdir}/usr/share/applications/${pkgname}.desktop"

    # Install icon
    install -Dm644 AppDir/ToonTownMultiTool.png "${pkgdir}/usr/share/pixmaps/${pkgname}.png"

    # Install license
    install -Dm644 LICENSE "${pkgdir}/usr/share/licenses/${pkgname}/LICENSE"
}
```

- [ ] **Step 3: Test the PKGBUILD locally**

Run from `~/Projects/aur-toontown-multitool`:

```bash
makepkg -si
```

Expected: Package builds, installs, and `toontown-multitool` launches the app. `ttmt` also works.

- [ ] **Step 4: Verify installed files**

```bash
pacman -Ql toontown-multitool
```

Expected output should include:
```
toontown-multitool /usr/bin/toontown-multitool
toontown-multitool /usr/bin/ttmt
toontown-multitool /usr/share/toontown-multitool/main.py
toontown-multitool /usr/share/applications/toontown-multitool.desktop
toontown-multitool /usr/share/pixmaps/toontown-multitool.png
toontown-multitool /usr/share/licenses/toontown-multitool/LICENSE
```

- [ ] **Step 5: Verify launch commands**

```bash
toontown-multitool &
# App should open
kill %1

ttmt &
# App should open
kill %1
```

- [ ] **Step 6: Generate .SRCINFO**

```bash
makepkg --printsrcinfo > .SRCINFO
```

- [ ] **Step 7: Commit**

```bash
git add PKGBUILD .SRCINFO
git commit -m "Initial PKGBUILD for toontown-multitool 2.0.1"
```

---

### Task 3: Publish to AUR

- [ ] **Step 1: Create AUR account**

Go to https://aur.archlinux.org/register and create an account. Add your SSH public key in the account settings (My Account -> SSH Public Key).

- [ ] **Step 2: Add AUR remote**

```bash
cd ~/Projects/aur-toontown-multitool
git remote add aur ssh://aur@aur.archlinux.org/toontown-multitool.git
```

- [ ] **Step 3: Push to AUR**

```bash
git push aur master
```

Expected: Package appears at `https://aur.archlinux.org/packages/toontown-multitool`

---

### Task 4: Update workflow for future releases

This is a reference for future version bumps, not an implementation step.

When releasing a new version (e.g. `v2.0.2`):

```bash
cd ~/Projects/aur-toontown-multitool

# 1. Update pkgver in PKGBUILD
sed -i 's/pkgver=.*/pkgver=2.0.2/' PKGBUILD

# 2. Update checksums
updpkgsums

# 3. Regenerate .SRCINFO
makepkg --printsrcinfo > .SRCINFO

# 4. Commit and push
git add PKGBUILD .SRCINFO
git commit -m "Update to 2.0.2"
git push aur master
```
