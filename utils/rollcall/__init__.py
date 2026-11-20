"""Roll Call: the install, update and uninstall windows, and the stage the
in-app update sheets share with them.

Four toon slots are the progress bar. A toon takes its place as each step
starts, everyone hops when it is done, and a missing toon is the error.

This package imports PySide6 and the standard library only (plus
``utils.version_compare``, which is itself pure). The windows run from a small
frozen build of their own, before the app is installed and while it is being
replaced, so nothing here may import the rest of the app.
"""
