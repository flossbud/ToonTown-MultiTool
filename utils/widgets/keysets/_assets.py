"""Back-compat shim: keysets' asset resolver now lives in utils.asset_paths."""
from utils.asset_paths import asset_path

__all__ = ["asset_path"]
