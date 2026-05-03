"""Compatibility shim — the Multitoon tab moved to the `tabs.multitoon` package.

This file lets `from tabs.multitoon_tab import MultitoonTab` keep working without
touching every call site.
"""

from tabs.multitoon import MultitoonTab

__all__ = ["MultitoonTab"]
