import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import inspect


def test_launch_tab_log_wrapper_forwards_level():
    from tabs.launch_tab import LaunchTab
    sig = inspect.signature(LaunchTab.log)
    assert "level" in sig.parameters
    assert sig.parameters["level"].default is None


def test_multitoon_log_wrapper_forwards_level():
    import tabs.multitoon._tab as mt
    # find the tab class defensively (name may not be MultitoonTab)
    import inspect as _i
    classes = [c for _n, c in _i.getmembers(mt, _i.isclass)
               if c.__module__ == mt.__name__ and hasattr(c, "log")]
    assert classes, "no class with a log method found in tabs.multitoon._tab"
    sig = _i.signature(classes[0].log)
    assert "level" in sig.parameters
    assert sig.parameters["level"].default is None


class _Rec:
    def __init__(self):
        self.calls = []

    def append_log(self, msg, level=None):
        self.calls.append((msg, level))


def test_wrappers_pass_level_through():
    from tabs.launch_tab import LaunchTab

    tab = LaunchTab.__new__(LaunchTab)     # skip heavy __init__
    tab.logger = _Rec()
    LaunchTab.log(tab, "boom", level="error")
    LaunchTab.log(tab, "plain")            # omitted level forwards None
    assert tab.logger.calls == [("boom", "error"), ("plain", None)]


def test_multitoon_wrapper_passes_level_through():
    import inspect as _i
    import tabs.multitoon._tab as mt
    cls = next(c for _n, c in _i.getmembers(mt, _i.isclass)
               if c.__module__ == mt.__name__ and hasattr(c, "log"))
    tab = cls.__new__(cls)                 # skip heavy __init__
    tab.logger = _Rec()
    cls.log(tab, "boom", level="warn")
    assert tab.logger.calls == [("boom", "warn")]
