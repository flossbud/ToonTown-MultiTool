"""Tests for the WineInstall dataclass and install_signature."""

from services.wine_runtimes import WineInstall, install_signature


def test_wineinstall_is_frozen():
    install = WineInstall(
        exe_path="/a/b/c.exe",
        launcher="bottles",
        prefix_path="/a/b",
        display_name="X",
        metadata={},
    )
    import dataclasses
    assert dataclasses.is_dataclass(install)
    try:
        install.launcher = "lutris"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("WineInstall should be frozen")


def test_install_signature_is_stable_for_same_inputs(tmp_path):
    exe = tmp_path / "CorporateClash.exe"
    exe.write_text("")
    a = WineInstall(exe_path=str(exe), launcher="wine", prefix_path=str(tmp_path),
                    display_name="A", metadata={})
    b = WineInstall(exe_path=str(exe), launcher="wine", prefix_path=str(tmp_path),
                    display_name="B-different-display", metadata={"x": 1})
    assert install_signature(a) == install_signature(b), (
        "signature should depend only on (launcher, prefix_path, exe_path)"
    )


def test_install_signature_differs_when_launcher_differs(tmp_path):
    exe = tmp_path / "CorporateClash.exe"
    exe.write_text("")
    a = WineInstall(exe_path=str(exe), launcher="wine", prefix_path=str(tmp_path),
                    display_name="A", metadata={})
    b = WineInstall(exe_path=str(exe), launcher="bottles", prefix_path=str(tmp_path),
                    display_name="A", metadata={})
    assert install_signature(a) != install_signature(b)
