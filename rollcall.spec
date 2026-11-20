# -*- mode: python ; coding: utf-8 -*-
#
# Roll Call: the install, update and uninstall windows Setup carries
# (packaging/windows/installer.iss). A small onedir build of its own:
# PySide6 QtCore/QtGui/QtWidgets, the stage art, the three typefaces, and
# nothing the app drags in. Built by CI before ISCC; Setup unpacks it to its
# temp folder on a double-click, so every megabyte here is time before the
# first pixel.
#
#   pyinstaller --noconfirm rollcall.spec      ->  dist/rollcall/rollcall.exe
#
# Smoke: dist/rollcall/rollcall.exe --self-check   (exit 0; 3 = art or type missing)

import sys

datas = [
    ('assets/rollcall', 'assets/rollcall'),
    ('assets/fonts/rollcall', 'assets/fonts/rollcall'),
    ('assets/logos/ttmt_logo_textonly.png', 'assets/logos'),
    ('assets/ToonTownMultiTool.ico', 'assets'),
]

# Loaded lazily by utils/rollcall/app.py.
hiddenimports = [
    'utils.rollcall.engine_inno',
    'utils.rollcall.installer',
    'utils.rollcall.updater',
    'utils.rollcall.uninstaller',
]
if sys.platform == 'win32':
    hiddenimports.append('utils.rollcall.winplat')

excludes = [
    # The app's world: none of it is imported from utils.rollcall.
    'requests', 'urllib3', 'certifi', 'charset_normalizer', 'idna',
    'pynput', 'keyring', 'jaraco', 'secretstorage', 'jeepney', 'Xlib',
    'win32api', 'win32com', 'win32comext', 'pywintypes', 'pythoncom',
    'PIL', 'numpy', 'objc', 'AppKit', 'Quartz',
    # Qt the windows do not use.
    'PySide6.QtNetwork', 'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuickWidgets',
    'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets', 'PySide6.QtSvg', 'PySide6.QtSvgWidgets',
    'PySide6.QtPdf', 'PySide6.QtMultimedia', 'PySide6.QtWebEngineCore', 'PySide6.QtDBus',
    'PySide6.QtPrintSupport', 'PySide6.QtXml', 'PySide6.QtConcurrent',
    # Standard library the windows never touch.
    'tkinter', 'unittest', 'pydoc', 'doctest', 'xmlrpc', 'sqlite3', 'lib2to3',
    'pdb', 'asyncio', 'ftplib', 'mailbox',
]

a = Analysis(
    ['rollcall_main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)


def _wanted(dest: str) -> bool:
    """Qt files the windows need. PNG and the fonts are built into QtGui;
    the window icon is an .ico (imageformats/qico); the folder picker is the
    native one (platforms/qwindows)."""
    d = dest.replace('\\', '/').lower()
    name = d.rsplit('/', 1)[-1]
    if '/translations/' in d or name.endswith('.qm'):
        return False
    for drop in ('opengl32sw', 'd3dcompiler', 'qt6pdf', 'qt6qml', 'qt6quick', 'qt6network',
                 'qt6opengl', 'qt6svg', 'qt6virtualkeyboard', 'qt6dbus', 'qt6printsupport'):
        if name.startswith(drop):
            return False
    if '/plugins/' in d:
        kind = d.split('/plugins/', 1)[1].split('/', 1)[0]
        if kind == 'imageformats':
            return name.startswith(('qico', 'libqico'))
        if sys.platform == 'win32':
            return kind in ('platforms', 'styles')
        return kind in ('platforms', 'platformthemes', 'xcbglintegrations', 'styles')
    return True


a.binaries = [entry for entry in a.binaries if _wanted(entry[0])]
a.datas = [entry for entry in a.datas if _wanted(entry[0])]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='rollcall',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    # A traceback dialog would block Setup, which waits on this process:
    # rollcall_main.py logs the error and exits 3 (Setup shows its wizard).
    disable_windowed_traceback=True,
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
    name='rollcall',
)
