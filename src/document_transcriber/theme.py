"""Square, low-glare work surfaces with restrained safety-orange accents."""

STYLE = """
* { border-radius: 0px; }
QMainWindow, QDialog { background: #101214; }
QWidget { color: #d8dadc; }
QToolTip { background: #25292c; color: #f5f5f5; border: 1px solid #52565a; padding: 6px; }
QMenuBar { background: #101214; color: #92989d; padding: 3px 14px; border-bottom: 1px solid #292d30; }
QMenuBar::item { padding: 4px 10px; }
QMenuBar::item:selected, QMenu::item:selected { background: #34302a; color: #ff9b55; }
QMenu { background: #1b1e21; border: 1px solid #3a3e42; padding: 5px; }
QMenu::item { padding: 8px 25px 8px 12px; }
QFrame#topbar { background: #141719; border-bottom: 1px solid #303438; }
QLabel#brand { color: #f0f1f2; font-size: 18px; font-weight: 800; letter-spacing: 3px; }
QLabel#eyebrow { color: #848c92; font-size: 10px; font-weight: 700; letter-spacing: 2px; }
QLabel#muted { color: #7f8991; font-size: 11px; }
QLabel#orange { color: #ff9147; font-size: 11px; font-weight: 600; }
QLabel#title { color: #f1f2f3; font-size: 20px; font-weight: 600; }
QLabel#section { color: #a6adb3; font-size: 10px; font-weight: 700; letter-spacing: 1.4px; }
QLabel#badge { color: #f59a5e; background: #2d241d; border: 1px solid #55402f; padding: 4px 7px; font-size: 10px; }
QFrame#sidebar, QFrame#inspector { background: #15181a; }
QScrollArea, QFrame#dictionary { background: #15181a; border: none; }
QFrame#sidebar { border-right: 1px solid #2b3034; }
QFrame#inspector { border-left: 1px solid #2b3034; }
QFrame#panelHeader { background: #191c1f; border-bottom: 1px solid #303438; }
QFrame#toolbar { background: #141719; border-bottom: 1px solid #2c3034; }
QFrame#footer { background: #15181a; border-top: 1px solid #2b3034; }
QFrame#rule { background: #303438; max-height: 1px; }
QPushButton, QToolButton { background: #23272a; color: #cbd0d4; border: 1px solid #3a4045; padding: 8px 12px; font-size: 11px; font-weight: 600; }
QPushButton:hover, QToolButton:hover { background: #303438; border-color: #62686d; color: #ffffff; }
QPushButton:pressed, QToolButton:pressed { background: #40352b; }
QPushButton:focus, QToolButton:focus { border-color: #f78b3d; }
QPushButton:disabled, QToolButton:disabled { color: #5d656b; background: #1b1e20; border-color: #2b3034; }
QPushButton#primary { background: #f28b42; color: #17120f; border: 1px solid #f28b42; font-weight: 800; }
QPushButton#primary:hover { background: #ffa563; border-color: #ffa563; }
QPushButton#primary:disabled { background: #4c3729; color: #8a6b54; border-color: #4c3729; }
QPushButton#flat { background: transparent; border: 1px solid transparent; color: #9ca4aa; }
QPushButton#flat:hover { background: #24292d; color: #f0f2f3; }
QPushButton:checked { background: #382b21; color: #ff9b55; border-color: #aa6636; }
QLineEdit, QSpinBox, QComboBox { background: #101315; border: 1px solid #353b40; padding: 8px; selection-background-color: #80512e; color: #d5d9dc; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #dd8547; }
QComboBox { padding-right: 20px; min-width: 90px; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView { background: #202427; selection-background-color: #57402d; color: #ddd; }
QPlainTextEdit { background: #141719; color: #d7dcdf; border: none; selection-background-color: #674b33; selection-color: #fff3e7; padding: 16px; }
QPlainTextEdit#notes { background: #101315; border: 1px solid #30373b; padding: 8px; }
QTreeWidget, QListWidget { background: transparent; border: none; outline: none; color: #b4bdc4; }
QTreeWidget::item, QListWidget::item { padding: 10px 5px; border-bottom: 1px solid #202529; }
QTreeWidget::item:selected, QListWidget::item:selected { background: #30281f; color: #ffad72; }
QTreeWidget::item:hover, QListWidget::item:hover { background: #25292c; }
QHeaderView::section { background: #1a1e21; color: #838d95; border: none; padding: 7px; font-size: 10px; }
QCheckBox { color: #a8b0b6; spacing: 7px; font-size: 11px; }
QCheckBox::indicator { width: 13px; height: 13px; border: 1px solid #626b72; background: #15181a; }
QCheckBox::indicator:checked { background: #f28b42; border: 3px solid #755033; }
QTabWidget::pane { border: none; border-top: 1px solid #30363b; }
QTabBar::tab { background: #15181a; color: #818c94; padding: 12px 13px; border-bottom: 2px solid transparent; font-size: 10px; font-weight: 700; }
QTabBar::tab:selected { color: #ff9b55; border-bottom-color: #f28b42; }
QSplitter::handle { background: #2a2f33; width: 2px; height: 2px; }
QScrollBar:vertical { background: #15181a; width: 7px; margin: 0; }
QScrollBar:horizontal { background: #15181a; height: 7px; margin: 0; }
QScrollBar::handle { background: #485057; min-height: 25px; min-width: 25px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QStatusBar { background: #0e1113; border-top: 1px solid #2a3034; color: #8e989f; font-size: 10px; }
QStatusBar::item { border: none; }
QProgressBar { border: none; background: #252a2e; max-height: 3px; }
QProgressBar::chunk { background: #f28b42; }
QMessageBox QLabel { min-width: 320px; }
"""
