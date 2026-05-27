"""Dark DAW-style Qt stylesheet."""

DARK_STYLE = """
/* ── Base ───────────────────────────────────────────────────── */
QMainWindow, QWidget, QDialog {
    background-color: #0e0e1a;
    color: #e0e0f0;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 9pt;
}

QSplitter::handle {
    background: #1e1e32;
    height: 4px;
    width: 4px;
}

/* ── Buttons ────────────────────────────────────────────────── */
QPushButton {
    background-color: #1e1e32;
    border: 1px solid #2e2e50;
    border-radius: 5px;
    padding: 5px 12px;
    color: #c0c0e0;
    min-height: 24px;
}
QPushButton:hover {
    background-color: #2a2a48;
    border-color: #7c6af7;
    color: #e8e8ff;
}
QPushButton:pressed {
    background-color: #3a2a70;
}
QPushButton:checked {
    background-color: #5040b0;
    border-color: #a89cff;
    color: #ffffff;
}
QPushButton:disabled {
    color: #404060;
    border-color: #1e1e32;
    background-color: #14141e;
}

/* ── Mute / Solo pill buttons ───────────────────────────────── */
QPushButton#muteBtn {
    background-color: #1e1e32;
    border-color: #444466;
    color: #888899;
    font-weight: bold;
    padding: 3px 7px;
    border-radius: 4px;
    min-height: 20px;
}
QPushButton#muteBtn:checked {
    background-color: #b85020;
    border-color: #ff8060;
    color: #ffe0d0;
}
QPushButton#soloBtn {
    background-color: #1e1e32;
    border-color: #444466;
    color: #888899;
    font-weight: bold;
    padding: 3px 7px;
    border-radius: 4px;
    min-height: 20px;
}
QPushButton#soloBtn:checked {
    background-color: #a07800;
    border-color: #ffcc00;
    color: #fff0a0;
}

/* ── Sliders ────────────────────────────────────────────────── */
QSlider::groove:vertical {
    background: #1a1a2e;
    width: 6px;
    border-radius: 3px;
    border: 1px solid #2a2a44;
}
QSlider::sub-page:vertical {
    background: qlineargradient(x1:0,y1:1,x2:0,y2:0, stop:0 #5040b0, stop:1 #a89cff);
    border-radius: 3px;
}
QSlider::handle:vertical {
    background: #a89cff;
    border: 1px solid #8070d0;
    width: 16px;
    height: 16px;
    border-radius: 8px;
    margin: 0 -5px;
}
QSlider::groove:horizontal {
    background: #1a1a2e;
    height: 6px;
    border-radius: 3px;
    border: 1px solid #2a2a44;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #5040b0, stop:1 #a89cff);
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #a89cff;
    border: 1px solid #8070d0;
    width: 16px;
    height: 16px;
    border-radius: 8px;
    margin: -5px 0;
}
QSlider::handle:hover {
    background: #c0b4ff;
}

/* ── Labels ─────────────────────────────────────────────────── */
QLabel {
    color: #c0c0e0;
    background: transparent;
}
QLabel#sectionLabel {
    color: #8080b0;
    font-size: 8pt;
    letter-spacing: 1px;
}
QLabel#songTitle {
    color: #e8e8ff;
    font-size: 11pt;
    font-weight: bold;
}
QLabel#timeLabel {
    color: #a89cff;
    font-size: 14pt;
    font-family: 'Courier New', monospace;
    font-weight: bold;
    letter-spacing: 2px;
}

/* ── Progress bar ───────────────────────────────────────────── */
QProgressBar {
    background-color: #1a1a2e;
    border: 1px solid #2e2e50;
    border-radius: 4px;
    text-align: center;
    color: #a89cff;
    height: 8px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #5040b0, stop:1 #a89cff);
    border-radius: 4px;
}

/* ── Scroll bars ─────────────────────────────────────────────── */
QScrollBar:vertical, QScrollBar:horizontal {
    background: #0e0e1a;
    width: 8px;
    height: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: #2e2e50;
    border-radius: 4px;
    min-height: 24px;
    min-width: 24px;
}
QScrollBar::handle:hover {
    background: #5040b0;
}
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }

/* ── Group boxes ─────────────────────────────────────────────── */
QGroupBox {
    border: 1px solid #2a2a44;
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 6px;
    color: #8080b0;
    font-size: 8pt;
    letter-spacing: 1px;
    text-transform: uppercase;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 5px;
}

/* ── Scroll area ─────────────────────────────────────────────── */
QScrollArea { border: none; background: transparent; }

/* ── Tool tip ────────────────────────────────────────────────── */
QToolTip {
    background-color: #1e1e32;
    border: 1px solid #5040b0;
    color: #e0e0ff;
    padding: 4px 8px;
    border-radius: 4px;
}

/* ── Dialog ──────────────────────────────────────────────────── */
QDialog {
    background-color: #0e0e1a;
}
"""

STEM_COLORS = {
    'vocals': '#ff6b9d',
    'drums':  '#ffa726',
    'bass':   '#ab47bc',
    'guitar': '#26c6da',
    'piano':  '#66bb6a',
    'other':  '#8d6e63',
}
