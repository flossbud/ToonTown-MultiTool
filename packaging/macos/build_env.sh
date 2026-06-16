# build_env.sh - pinned macOS build outputs, validated during the Task 3 bring-up.
# Sourced by build-macos.yml / test-macos.yml and exported into the PyInstaller
# spec env (TTMT_LSMINVER).
#
# GitHub no longer reliably serves Intel (macos-13) runners, so the universal2
# .app is built on ONE Apple-Silicon runner: the x86_64 slice under Rosetta 2,
# the arm64 slice natively, then lipo-merged. Both slices use the SAME
# python-build-standalone (PBS) interpreter so the two trees are structurally
# identical before lipo. Validated locally on Apple Silicon: both slices build,
# merge to a fully-fat bundle, sign under the hardened runtime, and --self-check
# clean (arm64 native AND x86_64 under Rosetta).
export PBS_RELEASE="20260610"      # python-build-standalone release tag
export PBS_PYTHON="3.12.13"        # cpython version (identical on both arches)
export TTMT_LSMINVER="12.0"        # max minOS across bundled Mach-O (Qt 6.8 floor)
# Informational: PySide6 both arches resolve from requirements.txt (the lock).
export PYSIDE_RESOLVED="6.8.3"
