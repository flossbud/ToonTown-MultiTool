# -*- mode: python ; coding: utf-8 -*-

import sys


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/ToonTownMultiTool.ico', 'assets')],
    hiddenimports=[
        'pynput.keyboard._xorg',
        'pynput.mouse._xorg',
        'pynput._util.xorg',
        'pynput._util.xorg_keysyms',
        'pynput.keyboard._win32',
        'pynput.mouse._win32',
        'pynput._util.win32',
        'pynput._util.win32_vks',
        'pynput.keyboard._darwin',
        'pynput.mouse._darwin',
        'pynput._util.darwin',
        'pynput._util.darwin_vks',
        'pynput.keyboard._uinput',
        'pynput._util.uinput',
        'keyring.backends.kwallet',
        'keyring.backends.libsecret',
        'keyring.backends.SecretService',
        'keyring.backends.chainer',
        'certifi',
        'secretstorage',
        'jeepney',
        'jeepney.io',
        'jeepney.io.blocking',
        'jeepney.bus_messages',
        'jeepney.wrappers',
        'utils.kwallet_jeepney',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

if sys.platform == "win32":
    # Windows: onedir + no UPX. Onefile extracts ~100MB of Qt DLLs to %TEMP%
    # on every launch, and Defender rescans every UPX-packed .pyd. Onedir
    # keeps the binaries on disk next to the .exe so the per-launch extraction
    # cost disappears and Defender only scans new files once.
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='ToonTownMultiTool',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon='assets/ToonTownMultiTool.ico',
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name='ToonTownMultiTool',
    )
else:
    # Linux: onefile. AppImage packaging expects a single binary at
    # dist/ToonTownMultiTool, and the per-launch extraction cost is a
    # non-issue without Defender-style real-time scanning.
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name='ToonTownMultiTool',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon='assets/ToonTownMultiTool.ico',
    )
