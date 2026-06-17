# PyInstaller spec for the minimal .app parent used by the TCC attribution spike
# (Phase 0, THROWAWAY). `*.spec` is gitignored, so this is force-added.
#
# Build (any python with PyInstaller; the PARENT's platform-bit is irrelevant - only the
# spawned /usr/bin/python3 child posts events):
#   <py> -m PyInstaller --noconfirm scripts/macos_clicksync_spike.spec
# Then verify the helper + delivery module landed in the bundle (Resources or Frameworks):
#   find dist/ttmt-cs-spike.app -name 'macos_clicksync_ctypes_spike.py' -o -name 'macos_mouse_delivery.py'

block_cipher = None

# NOTE: PyInstaller 6.x resolves relative paths in a .spec against the spec's own
# directory (SPECPATH = scripts/), so these are written relative to scripts/.
a = Analysis(
    ['macos_clicksync_spike_app.py'],
    pathex=[],
    binaries=[],
    # ship the inject helper + the pyobjc-free delivery engine flat, so the helper's
    # sys.path.insert(0, dirname(__file__)) resolves `import macos_mouse_delivery`.
    datas=[
        ('macos_clicksync_ctypes_spike.py', '.'),
        ('../utils/macos_mouse_delivery.py', '.'),
    ],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter'],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='ttmt-cs-spike',
    console=False,   # GUI app -> launches in the Aqua session
)
coll = COLLECT(exe, a.binaries, a.datas, name='ttmt-cs-spike')
app = BUNDLE(
    coll,
    name='ttmt-cs-spike.app',
    bundle_identifier='com.flossbud.ttmt.csspike',
    info_plist={
        'NSInputMonitoringUsageDescription': 'TCC attribution spike',
        'LSMinimumSystemVersion': '12.0',
    },
)
