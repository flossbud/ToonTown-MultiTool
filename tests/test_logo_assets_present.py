import os


def test_logo_assets_exist():
    """Both header logo variants must ship. Packaging includes assets/
    wholesale (PyInstaller ('assets','assets'); Flatpak `cp -r assets`), so
    this guards against the files being moved/renamed out from under the
    header loader."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    logos = os.path.join(here, "assets", "logos")
    for fname in ("ttmt_logo_textonly.png", "ttmt_logo_textonly_shadow.png"):
        assert os.path.isfile(os.path.join(logos, fname)), f"missing {fname}"
