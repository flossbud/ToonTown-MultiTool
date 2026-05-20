"""Tests for install_set_hash — stable hash of a set of WineInstalls."""

from services.wine_runtimes import WineInstall, install_set_hash, install_signature


def _mk(name, launcher="bottles"):
    return WineInstall(
        exe_path=f"/x/{name}/CorporateClash.exe",
        launcher=launcher,
        prefix_path=f"/x/{name}",
        display_name=f"{launcher} · {name}",
        metadata={},
    )


def test_empty_list_returns_empty_string():
    assert install_set_hash([]) == ""


def test_single_install_returns_nonempty():
    h = install_set_hash([_mk("A")])
    assert h
    assert len(h) == 16


def test_same_set_same_hash():
    s1 = install_set_hash([_mk("A"), _mk("B")])
    s2 = install_set_hash([_mk("A"), _mk("B")])
    assert s1 == s2


def test_order_independent():
    a, b = _mk("A"), _mk("B")
    assert install_set_hash([a, b]) == install_set_hash([b, a])


def test_different_sets_different_hashes():
    a, b, c = _mk("A"), _mk("B"), _mk("C")
    assert install_set_hash([a, b]) != install_set_hash([a, c])
    assert install_set_hash([a]) != install_set_hash([a, b])


def test_hash_is_function_of_signatures_only():
    """Two installs with identical (exe_path, launcher, prefix_path) but
    different display_name / metadata produce the same set-hash, because
    install_signature ignores those fields."""
    a1 = WineInstall("/x/A/CorporateClash.exe", "bottles", "/x/A",
                     "Bottles · A", {"bottle_name": "A"})
    a2 = WineInstall("/x/A/CorporateClash.exe", "bottles", "/x/A",
                     "DIFFERENT DISPLAY", {"bottle_name": "DIFFERENT"})
    assert install_signature(a1) == install_signature(a2)
    assert install_set_hash([a1]) == install_set_hash([a2])
