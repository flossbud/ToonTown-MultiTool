"""Grandstand launcher widgets (2026-08-14 spec, sub-project A).

Leaf package: these widgets never import a tab module. Colours come from
`palette`, whose only Qt dependency is QColor. Selection state comes from
`party` and display values from `model`; both are Qt-free and unit-testable.
"""
