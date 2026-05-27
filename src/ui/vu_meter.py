"""
LED-style stereo VU meter widget.
Reads peak level from a shared numpy array (set externally at ~60 fps).
"""

import math
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QPainter, QColor, QLinearGradient


# dB levels for LED segments (top = 0 dBFS, bottom = -60 dBFS)
_SEGMENTS = 24          # number of LED segments
_PEAK_HOLD_MS = 1500    # milliseconds before peak indicator falls
_PEAK_FALL_MS = 50      # how often peak falls (ms per step)
_PEAK_FALL_STEP = 1     # segments to drop per fall tick


def _linear_to_db(linear: float) -> float:
    if linear <= 0.0:
        return -80.0
    return 20.0 * math.log10(max(linear, 1e-10))


def _db_to_segment(db: float, n: int = _SEGMENTS) -> int:
    """Map dB value (-60..0) to segment index 0..n-1."""
    clamped = max(-60.0, min(0.0, db))
    return int((clamped + 60.0) / 60.0 * n)


# Colour thresholds (segment index from bottom)
_GREEN_END  = int(_SEGMENTS * 0.70)   # 0 – 70% green
_YELLOW_END = int(_SEGMENTS * 0.90)   # 70 – 90% yellow
# above 90% = red


class VUMeter(QWidget):
    """Stereo LED VU meter. Set .level_l and .level_r (0.0–1.0) to update."""

    def __init__(self, parent=None, orientation=Qt.Vertical):
        super().__init__(parent)
        self._orientation = orientation
        self.level_l: float = 0.0
        self.level_r: float = 0.0
        self._peak_l: int = 0
        self._peak_r: int = 0
        self._peak_hold_l: int = 0
        self._peak_hold_r: int = 0

        if orientation == Qt.Vertical:
            self.setMinimumSize(22, 80)
            self.setMaximumWidth(30)
        else:
            self.setMinimumSize(80, 22)
            self.setMaximumHeight(30)

        # Peak decay timer
        self._decay_timer = QTimer(self)
        self._decay_timer.setInterval(_PEAK_FALL_MS)
        self._decay_timer.timeout.connect(self._decay_peaks)
        self._decay_timer.start()

    def set_levels(self, left: float, right: float):
        self.level_l = left
        self.level_r = right

        seg_l = _db_to_segment(_linear_to_db(left))
        seg_r = _db_to_segment(_linear_to_db(right))

        if seg_l >= self._peak_l:
            self._peak_l = seg_l
            self._peak_hold_l = _PEAK_HOLD_MS // _PEAK_FALL_MS
        if seg_r >= self._peak_r:
            self._peak_r = seg_r
            self._peak_hold_r = _PEAK_HOLD_MS // _PEAK_FALL_MS

        self.update()

    def _decay_peaks(self):
        if self._peak_hold_l > 0:
            self._peak_hold_l -= 1
        elif self._peak_l > 0:
            self._peak_l = max(0, self._peak_l - _PEAK_FALL_STEP)

        if self._peak_hold_r > 0:
            self._peak_hold_r -= 1
        elif self._peak_r > 0:
            self._peak_r = max(0, self._peak_r - _PEAK_FALL_STEP)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)

        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor('#0a0a14'))

        if self._orientation == Qt.Vertical:
            self._draw_vertical(p, w, h)
        else:
            self._draw_horizontal(p, w, h)

    def _draw_vertical(self, p: QPainter, w: int, h: int):
        ch_w = (w - 4) // 2   # channel width
        gap = 2
        seg_h = max(2, (h - gap * (_SEGMENTS - 1)) // _SEGMENTS)

        for ch_idx, (level, peak) in enumerate(
            [(self.level_l, self._peak_l), (self.level_r, self._peak_r)]
        ):
            x = ch_idx * (ch_w + gap) + 1
            seg_count = _db_to_segment(_linear_to_db(level))

            for s in range(_SEGMENTS):
                y = h - (s + 1) * (seg_h + gap) + gap
                rect = QRectF(x, y, ch_w, seg_h)

                if s < seg_count:
                    colour = self._seg_colour(s, lit=True)
                else:
                    colour = self._seg_colour(s, lit=False)

                p.fillRect(rect, colour)

            # Peak indicator
            if 0 < peak <= _SEGMENTS:
                py = h - peak * (seg_h + gap) + gap
                p.fillRect(QRectF(x, py, ch_w, seg_h), QColor('#ffffff'))

    def _draw_horizontal(self, p: QPainter, w: int, h: int):
        ch_h = (h - 4) // 2
        gap = 2
        seg_w = max(2, (w - gap * (_SEGMENTS - 1)) // _SEGMENTS)

        for ch_idx, (level, peak) in enumerate(
            [(self.level_l, self._peak_l), (self.level_r, self._peak_r)]
        ):
            y = ch_idx * (ch_h + gap) + 1
            seg_count = _db_to_segment(_linear_to_db(level))

            for s in range(_SEGMENTS):
                x = s * (seg_w + gap)
                rect = QRectF(x, y, seg_w, ch_h)
                p.fillRect(rect, self._seg_colour(s, s < seg_count))

            if 0 < peak <= _SEGMENTS:
                px = (peak - 1) * (seg_w + gap)
                p.fillRect(QRectF(px, y, seg_w, ch_h), QColor('#ffffff'))

    @staticmethod
    def _seg_colour(seg: int, lit: bool) -> QColor:
        if lit:
            if seg < _GREEN_END:
                return QColor('#00cc44')
            elif seg < _YELLOW_END:
                return QColor('#ccaa00')
            else:
                return QColor('#cc2200')
        else:
            if seg < _GREEN_END:
                return QColor('#003311')
            elif seg < _YELLOW_END:
                return QColor('#332800')
            else:
                return QColor('#330800')
