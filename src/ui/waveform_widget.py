"""
Waveform display widget. Shows waveform envelope + playhead for one stem.
Supports click-to-seek.
"""

import numpy as np
from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import Qt, Signal, QRect, QPoint
from PySide6.QtGui import QPainter, QColor, QPen, QLinearGradient, QBrush


class WaveformWidget(QWidget):
    """Draws a stem's waveform envelope and a moveable playhead."""

    seek_requested = Signal(float)   # fraction 0.0–1.0

    def __init__(self, stem_name: str, color: str = '#7c6af7', parent=None):
        super().__init__(parent)
        self._name = stem_name
        self._color = QColor(color)
        self._peaks: np.ndarray = np.zeros((0, 2), dtype=np.float32)  # (n, [max, min])
        self._position_frac: float = 0.0
        self._dragging = False

        self.setMinimumHeight(48)
        self.setMaximumHeight(72)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)

    def set_peaks(self, peaks: np.ndarray):
        """peaks: (n, 2) float32 with [max, min] per column."""
        self._peaks = peaks
        self.update()

    def set_position(self, fraction: float):
        """fraction: 0.0 – 1.0"""
        self._position_frac = max(0.0, min(1.0, fraction))
        self.update()

    # ── Painting ──────────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)

        w, h = self.width(), self.height()
        mid = h // 2

        # Background
        p.fillRect(0, 0, w, h, QColor('#0d0d1a'))

        # Waveform
        if len(self._peaks) > 0:
            n = len(self._peaks)
            col_base = self._color
            col_dim = QColor(
                col_base.red() // 3,
                col_base.green() // 3,
                col_base.blue() // 3,
            )
            playhead_x = int(self._position_frac * w)

            for i in range(min(n, w)):
                x = int(i * w / n)
                peak_max = float(self._peaks[i, 0])
                peak_min = float(self._peaks[i, 1])

                y_top = int(mid - peak_max * (mid - 2))
                y_bot = int(mid - peak_min * (mid - 2))

                colour = col_dim if x < playhead_x else col_base
                p.setPen(QPen(colour, 1))
                p.drawLine(x, y_top, x, y_bot)

        # Centre line
        centre_col = QColor(
            self._color.red() // 2,
            self._color.green() // 2,
            self._color.blue() // 2,
        )
        p.setPen(QPen(centre_col, 1))
        p.drawLine(0, mid, w, mid)

        # Stem label (top-left)
        from src.stem_manager import STEM_LABELS
        label = STEM_LABELS.get(self._name, self._name.capitalize())
        p.setPen(QPen(QColor('#808090'), 1))
        p.setFont(self.font())
        p.drawText(6, 13, label)

        # Playhead
        if len(self._peaks) > 0:
            px = int(self._position_frac * w)
            p.setPen(QPen(QColor('#ffffff'), 2))
            p.drawLine(px, 0, px, h)

        # Border bottom
        p.setPen(QPen(QColor('#1e1e32'), 1))
        p.drawLine(0, h - 1, w, h - 1)

    # ── Mouse interaction ─────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and len(self._peaks) > 0:
            self._dragging = True
            self._emit_seek(event.position().x())

    def mouseMoveEvent(self, event):
        if self._dragging and len(self._peaks) > 0:
            self._emit_seek(event.position().x())

    def mouseReleaseEvent(self, event):
        self._dragging = False

    def _emit_seek(self, mouse_x: float):
        frac = max(0.0, min(1.0, mouse_x / self.width()))
        self.seek_requested.emit(frac)
