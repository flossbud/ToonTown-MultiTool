from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

DARK_THEME = """
    QWidget {
        font-family: 'Segoe UI', 'Inter', sans-serif;
        font-size: 11.5pt;
        background-color: #2c2c2c;
        color: #e0e0e0;
    }
    QTabWidget::pane {
        border: 1px solid #555;
        border-radius: 8px;
        margin-top: -1px;
        background-color: #3e3e3e;
    }
    QTabBar::tab {
        background-color: #383838;
        color: #bbbbbb;
        padding: 6px 14px;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        margin-right: 2px;
    }
    QTabBar::tab:selected {
        background-color: #505050;
        color: white;
        font-weight: bold;
    }
    QTabBar::tab:hover {
        background-color: #4a4a4a;
        color: #dddddd;
    }
    QPushButton {
        background-color: #4a4a4a;
        color: white;
        border-radius: 6px;
        padding: 6px 12px;
        border: 1px solid #666;
    }
    QPushButton:hover {
        background-color: #5a5a5a;
        border: 1px solid #80c080;
    }
    QComboBox {
        background-color: #4a4a4a;
        color: white;
        border-radius: 6px;
        padding: 4px 8px;
        border: 1px solid #666;
    }
    QComboBox QAbstractItemView {
        background-color: #3a3a3a;
        selection-background-color: #5a5a5a;
        color: white;
    }
"""

LIGHT_THEME = """
    QWidget {
        font-family: 'Segoe UI', 'Inter', sans-serif;
        font-size: 11.5pt;
        background-color: #f5f5f5;
        color: #202020;
    }
    QTabWidget::pane {
        border: 1px solid #bbb;
        border-radius: 8px;
        margin-top: -1px;
        background-color: #ffffff;
    }
    QTabBar::tab {
        background-color: #e8e8e8;
        color: #222;
        padding: 6px 14px;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        margin-right: 2px;
    }
    QTabBar::tab:selected {
        background-color: #ffffff;
        color: black;
        font-weight: bold;
    }
    QTabBar::tab:hover {
        background-color: #dddddd;
        color: black;
    }
    QPushButton {
        background-color: #eeeeee;
        color: #111;
        border-radius: 6px;
        padding: 6px 12px;
        border: 1px solid #aaa;
    }
    QPushButton:hover {
        background-color: #dddddd;
        border: 1px solid #66aa66;
    }
    QComboBox {
        background-color: #ffffff;
        color: #111;
        border-radius: 6px;
        padding: 4px 8px;
        border: 1px solid #aaa;
    }
    QComboBox QAbstractItemView {
        background-color: #f8f8f8;
        selection-background-color: #e0e0e0;
        color: #111;
    }
"""



def resolve_theme(settings_manager):
    user_pref = settings_manager.get("theme", "system")
    if user_pref in ("light", "dark"):
        return user_pref

    palette = QApplication.instance().palette()
    base_color = palette.color(QPalette.Base)
    return "dark" if base_color.value() < 128 else "light"


def apply_theme(app, theme):
    if theme == "dark":
        app.setStyleSheet(DARK_THEME)
    elif theme == "light":
        app.setStyleSheet(LIGHT_THEME)
    else:
        app.setStyleSheet("")
