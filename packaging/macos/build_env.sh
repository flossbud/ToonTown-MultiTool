# build_env.sh - pinned macOS build outputs. Single source of truth, sourced by
# the workflows and exported into the PyInstaller spec env (TTMT_LSMINVER).
#
# These are PINNED during the Task 3 universal2 bring-up on CI: both the Intel
# (x86_64) and Apple-Silicon (arm64) runners MUST install the same BUILD_PY and
# PYSIDE_PIN against a hashed requirements lock, so the two .app trees are
# structurally identical before lipo merges them. LSMINVER is the min-OS tag of
# the resolved PySide6 wheel (the floor below which the app will not launch).
#
# Values below are the starting hypothesis; the bring-up replaces them with the
# empirically-resolved versions and re-commits this file.
export TTMT_LSMINVER="13.0"        # PySide6 wheel min-OS tag -> LSMinimumSystemVersion
export BUILD_PY="3.12"             # build Python minor (identical on both arches)
export PYSIDE_PIN="PySide6==6.8.3" # exact PySide6 both arches resolve
