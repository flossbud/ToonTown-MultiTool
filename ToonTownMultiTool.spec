# -*- mode: python ; coding: utf-8 -*-

import sys


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets', 'assets'),
        ('tools/wine_input_bridge/TTMTWineInputBridge.cs', 'tools/wine_input_bridge'),
    ],
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
elif sys.platform == "darwin":
    # macOS: a .app BUNDLE (onedir inside). The universal2 fat merge + ad-hoc
    # signing happen in CI AFTER this build (packaging/macos/*). Bundle metadata
    # comes from the build env (TTMT_VERSION / TTMT_BUILD_NUMBER / TTMT_LSMINVER)
    # plus the flavor (TTMT_BETA) so stable/beta get distinct id + name.
    import os
    sys.path.insert(0, SPECPATH)
    from utils.build_flavor import is_beta, bundle_id

    _beta = is_beta()
    _app_name = "ToonTown MultiTool Beta" if _beta else "ToonTown MultiTool"
    _ver = os.environ.get("TTMT_VERSION", "0.0.0")
    _build = os.environ.get("TTMT_BUILD_NUMBER", "0")
    _minver = os.environ.get("TTMT_LSMINVER", "12.0")
    _icns = os.path.join("assets", "ToonTownMultiTool.icns")
    if not os.path.exists(_icns):
        _icns = None   # generic icon until the .icns is generated (follow-up)

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
        icon=_icns,
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
    app = BUNDLE(
        coll,
        name=f"{_app_name}.app",
        icon=_icns,
        bundle_identifier=bundle_id(),
        version=_ver,
        info_plist={
            'CFBundleName': _app_name,
            'CFBundleDisplayName': _app_name,
            'CFBundleShortVersionString': _ver,
            'CFBundleVersion': _build,
            'LSMinimumSystemVersion': _minver,
            'NSHighResolutionCapable': True,
            'LSUIElement': False,
            'NSInputMonitoringUsageDescription':
                'ToonTown MultiTool forwards your keystrokes and clicks to your '
                'background toons.',
        },
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
