"""
ChordDisplayWidget — shows the currently playing chord in real time.
Updated externally via set_chord() from the position timer (~30 fps).
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QFontMetrics

from src.chord_detector import ChordEvent, QUALITY_COLOR


_QUALITY_NAMES: dict[str, str] = {
    'maj':   'Mayor',
    'min':   'Menor',
    '7':     'Séptima dom.',
    'maj7':  'Mayor 7ª',
    'min7':  'Menor 7ª',
    'sus2':  'Sus. 2ª',
    'sus4':  'Sus. 4ª',
    'dim':   'Disminuido',
    'aug':   'Aumentado',
    'dim7':  'Dim. 7ª',
    'hdim7': 'Semi-dim.',
}

_IDLE_COLOR = '#3a3a5a'
_NO_CHORD   = '—'


class ChordDisplayWidget(QWidget):
    """
    Compact strip showing the current chord name and quality.
    Height is fixed at 78 px so it fits neatly between the
    transport bar and the mixer splitter.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._event: ChordEvent | None = None
        self._chord_str: str = ''       # cached to skip redundant repaints
        self.setFixedHeight(78)
        self._build_ui()

    # ── Construction ──────────────────────────────────────────────────

    def _build_ui(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 6, 20, 6)
        lay.setSpacing(14)

        # "ACORDE" section label (rotated feel via small caps trick)
        header = QLabel("ACORDE")
        header.setStyleSheet(
            "color: #2e2e4a;"
            "font-size: 7pt;"
            "font-weight: bold;"
            "letter-spacing: 3px;"
        )
        header.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setFixedWidth(54)

        # Large chord name
        self._name_lbl = QLabel(_NO_CHORD)
        chord_font = QFont("Segoe UI", 28, QFont.Bold)
        self._name_lbl.setFont(chord_font)
        self._name_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._name_lbl.setStyleSheet(f"color: {_IDLE_COLOR};")
        self._name_lbl.setMinimumWidth(120)

        # Quality description
        self._desc_lbl = QLabel("")
        self._desc_lbl.setStyleSheet("color: #505070; font-size: 9pt;")
        self._desc_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        # Confidence bar (3 small dots)
        self._conf_lbl = QLabel("")
        self._conf_lbl.setStyleSheet("color: #303050; font-size: 10pt; letter-spacing: 2px;")
        self._conf_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        right_col = QVBoxLayout()
        right_col.setSpacing(2)
        right_col.addWidget(self._desc_lbl, alignment=Qt.AlignLeft)
        right_col.addWidget(self._conf_lbl, alignment=Qt.AlignLeft)

        lay.addWidget(header)
        lay.addWidget(self._name_lbl)
        lay.addLayout(right_col)
        lay.addStretch()

    # ── Public API ─────────────────────────────────────────────────────

    def set_chord(self, event: ChordEvent | None):
        """Update display. No-op when chord hasn't changed."""
        new_str = event.chord if event else ''
        if new_str == self._chord_str:
            return
        self._chord_str = new_str
        self._event = event

        if not event or event.chord in ('N', ''):
            self._name_lbl.setText(_NO_CHORD)
            self._name_lbl.setStyleSheet(f'color: {_IDLE_COLOR};')
            self._desc_lbl.setText('')
            self._conf_lbl.setText('')
        else:
            color = QUALITY_COLOR.get(event.quality, '#a89cff')
            self._name_lbl.setText(event.chord)
            self._name_lbl.setStyleSheet(f'color: {color};')
            self._desc_lbl.setText(_QUALITY_NAMES.get(event.quality, ''))
            self._conf_lbl.setText(_conf_dots(event.confidence))

        self.update()  # trigger paintEvent for background glow

    def clear(self):
        self.set_chord(None)

    # ── Painting ───────────────────────────────────────────────────────

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Background
        bg = QColor('#0f0f1c')
        p.setBrush(QBrush(bg))

        if self._event and self._event.chord not in ('N', '', _NO_CHORD):
            accent = QColor(QUALITY_COLOR.get(self._event.quality, '#7c6af7'))

            # Subtle glow fill
            fill = QColor(accent)
            fill.setAlpha(14)
            p.setBrush(QBrush(fill))

            # Colored border
            border = QColor(accent)
            border.setAlpha(55)
            p.setPen(QPen(border, 1))
        else:
            p.setPen(QPen(QColor('#1a1a2e'), 1))

        p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 6, 6)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _conf_dots(confidence: float) -> str:
    """Render confidence as 1–3 filled dots."""
    filled = max(1, round(confidence * 3))
    return '●' * filled + '○' * (3 - filled)
