# -*- mode: python ; coding: utf-8 -*-
# Minimal .app BUNDLE for the framework-python provenance spike. Mirrors the
# darwin branch of ToonTownMultiTool.spec but bundles ONLY what the spike needs:
# the entrypoint, the production delivery engine (utils/), PySide6, PyObjC. New
# bundle id so it gets its OWN TCC grant (does not pollute the real app's
# permissions). The entrypoint drives utils.macos_mouse_delivery directly, so
# PyInstaller analyzes the real delivery module natively - no script bundling.
import os

a = Analysis(
    ['macos_framework_spike.py'],
    pathex=[os.path.abspath(os.path.join(SPECPATH, '..'))],  # repo root: utils/ importable
    binaries=[],
    datas=[],
    hiddenimports=[
        'utils.macos_mouse_delivery',
        'utils.macos_discovery',
        'Quartz', 'AppKit', 'objc',
    ],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=['tkinter'],
    noarchive=False, optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name='FrameworkSpike', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, disable_windowed_traceback=False,
    argv_emulation=False, target_arch=None, codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, upx_exclude=[],
               name='FrameworkSpike')
app = BUNDLE(
    coll, name='Framework Spike.app', icon=None,
    bundle_identifier='com.flossbud.ttmt.frameworkspike',
    info_plist={
        'CFBundleName': 'Framework Spike',
        'LSMinimumSystemVersion': '12.0',
        'NSHighResolutionCapable': True,
        'LSUIElement': False,
        'NSInputMonitoringUsageDescription':
            'Framework spike posts synthetic input to a background toon.',
    },
)
