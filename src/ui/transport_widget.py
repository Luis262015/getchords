"""
Transport controls: play/pause, stop, seek bar, time display,
master volume, tempo (speed), and A-B loop.
"""

from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QPushButton, QSlider, QFrame
)
from PySide6.QtCore import Qt, Signal, QRect
from PySide6.QtGui import QPainter, QColor, QPen, QMouseEvent, QFont, QLinearGradient


class SeekBar(QWidget):
    """Clickable / draggable seek bar with gradient fill and A-B loop markers."""

    seek_requested = Signal(float)   # 0.0 – 1.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frac: float = 0.0
        self._frac_a: Optional[float] = None
        self._frac_b: Optional[float] = None
        self._dragging = False
        self.setFixedHeight(14)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Buscar posición  |  A/B: marcadores de loop")

    def set_position(self, frac: float):
        self._frac = max(0.0, min(1.0, frac))
        self.update()

    def set_loop_markers(self, frac_a: Optional[float], frac_b: Optional[float]):
        self._frac_a = frac_a
        self._frac_b = frac_b
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        bar_y, bar_h = 4, h - 8

        # ── Track background ─────────────────────────────────────────
        p.setPen(Qt.NoPen)
        p.setBrush(QColor('#1a1a2e'))
        p.drawRoundedRect(0, bar_y, w, bar_h, 3, 3)

        # ── Loop region highlight ────────────────────────────────────
        if (self._frac_a is not None and self._frac_b is not None
                and self._frac_b > self._frac_a):
            ax = int(self._frac_a * w)
            bx = int(self._frac_b * w)
            p.setBrush(QColor(80, 200, 120, 55))
            p.drawRect(ax, bar_y, bx - ax, bar_h)

        # ── Playback fill ────────────────────────────────────────────
        fill_w = int(self._frac * w)
        if fill_w > 0:
            grad = QLinearGradient(0, 0, fill_w, 0)
            grad.setColorAt(0, QColor('#5040b0'))
            grad.setColorAt(1, QColor('#a89cff'))
            p.setBrush(grad)
            p.drawRoundedRect(0, bar_y, fill_w, bar_h, 3, 3)

        # ── A marker ─────────────────────────────────────────────────
        if self._frac_a is not None:
            ax = int(self._frac_a * w)
            p.setPen(QPen(QColor('#50c878'), 2))
            p.setBrush(QColor('#50c878'))
            p.drawLine(ax, 0, ax, h)
            # Small "A" flag above the bar
            p.setFont(QFont("Segoe UI", 5, QFont.Bold))
            p.setPen(QColor('#50c878'))
            p.drawText(QRect(ax + 2, 0, 10, 7), Qt.AlignLeft | Qt.AlignVCenter, "A")

        # ── B marker ─────────────────────────────────────────────────
        if self._frac_b is not None:
            bx = int(self._frac_b * w)
            p.setPen(QPen(QColor('#ff6060'), 2))
            p.setBrush(QColor('#ff6060'))
            p.drawLine(bx, 0, bx, h)
            p.setFont(QFont("Segoe UI", 5, QFont.Bold))
            p.setPen(QColor('#ff6060'))
            p.drawText(QRect(bx - 12, 0, 10, 7), Qt.AlignRight | Qt.AlignVCenter, "B")

        # ── Playhead thumb ───────────────────────────────────────────
        tx = int(self._frac * w)
        p.setPen(QPen(QColor('#a89cff'), 1))
        p.setBrush(QColor('#e0d8ff'))
        p.drawEllipse(tx - 6, 1, 12, h - 2)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._emit(event.position().x())

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            self._emit(event.position().x())

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._dragging = False

    def _emit(self, x: float):
        self.seek_requested.emit(max(0.0, min(1.0, x / self.width())))


class TransportWidget(QWidget):
    """
    Signals:
        play_pause_clicked
        stop_clicked
        seek_requested(float)          – fraction 0–1
        master_volume_changed(float)   – 0–1.5
        tempo_changed(float)           – speed factor 0.25–2.0
        set_loop_a_clicked             – mark current position as loop A
        set_loop_b_clicked             – mark current position as loop B
        clear_loop_clicked             – remove A-B loop
    """

    play_pause_clicked    = Signal()
    stop_clicked          = Signal()
    seek_requested        = Signal(float)
    master_volume_changed = Signal(float)
    tempo_changed         = Signal(float)
    set_loop_a_clicked    = Signal()
    set_loop_b_clicked    = Signal()
    clear_loop_clicked    = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._playing = False
        self._total_sec: float = 0.0
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 6)
        root.setSpacing(4)

        # ── Song title ───────────────────────────────────────────────
        self.song_title = QLabel("Sin archivo cargado")
        self.song_title.setObjectName("songTitle")
        self.song_title.setAlignment(Qt.AlignCenter)
        root.addWidget(self.song_title)

        # ── Seek bar ─────────────────────────────────────────────────
        self.seek_bar = SeekBar()
        self.seek_bar.seek_requested.connect(self.seek_requested)
        root.addWidget(self.seek_bar)

        # ── Main controls row ─────────────────────────────────────────
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)

        self.stop_btn = QPushButton("⏹")
        self.stop_btn.setFixedSize(36, 36)
        self.stop_btn.setToolTip("Detener")
        self.stop_btn.clicked.connect(self.stop_clicked)
        ctrl_row.addWidget(self.stop_btn)

        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedSize(48, 48)
        self.play_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 #5040b0, stop:1 #8060d0);
                border: none; border-radius: 24px;
                font-size: 18pt; color: white;
            }
            QPushButton:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                stop:0 #6050c0, stop:1 #9070e0); }
            QPushButton:pressed { background: #4030a0; }
        """)
        self.play_btn.setToolTip("Reproducir / Pausar  (Espacio)")
        self.play_btn.clicked.connect(self.play_pause_clicked)
        ctrl_row.addWidget(self.play_btn)

        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setObjectName("timeLabel")
        self.time_label.setAlignment(Qt.AlignCenter)
        ctrl_row.addWidget(self.time_label, stretch=1)

        # Volume
        vol_frame = QFrame()
        vol_lay = QVBoxLayout(vol_frame)
        vol_lay.setContentsMargins(0, 0, 0, 0)
        vol_lay.setSpacing(2)
        vol_lbl = QLabel("Volumen")
        vol_lbl.setObjectName("sectionLabel")
        vol_lbl.setAlignment(Qt.AlignCenter)
        vol_lay.addWidget(vol_lbl)
        self.vol_slider = QSlider(Qt.Horizontal)
        self.vol_slider.setRange(0, 150)
        self.vol_slider.setValue(100)
        self.vol_slider.setFixedWidth(90)
        self.vol_slider.setToolTip("Volumen maestro")
        self.vol_slider.valueChanged.connect(
            lambda v: self.master_volume_changed.emit(v / 100.0)
        )
        vol_lay.addWidget(self.vol_slider)
        ctrl_row.addWidget(vol_frame)

        root.addLayout(ctrl_row)

        # ── Bottom row: Tempo + Loop A-B ─────────────────────────────
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)

        # ── Tempo section ─────────────────────────────────────────────
        tempo_frame = QFrame()
        tempo_frame.setStyleSheet(
            "QFrame { background: #161628; border-radius: 8px; }"
        )
        tempo_lay = QVBoxLayout(tempo_frame)
        tempo_lay.setContentsMargins(10, 6, 10, 6)
        tempo_lay.setSpacing(5)

        t_lbl = QLabel("TEMPO")
        t_lbl.setObjectName("sectionLabel")
        t_lbl.setAlignment(Qt.AlignCenter)
        tempo_lay.addWidget(t_lbl)

        tempo_ctrl = QHBoxLayout()
        tempo_ctrl.setSpacing(6)

        self.tempo_slider = QSlider(Qt.Horizontal)
        self.tempo_slider.setRange(25, 200)
        self.tempo_slider.setValue(100)
        self.tempo_slider.setMinimumWidth(80)
        self.tempo_slider.setToolTip("Velocidad de reproducción (25 % – 200 %)")
        self.tempo_slider.valueChanged.connect(self._on_tempo_slider)
        tempo_ctrl.addWidget(self.tempo_slider, stretch=1)

        self.tempo_val_lbl = QLabel("100%")
        self.tempo_val_lbl.setStyleSheet(
            "color: #a89cff; font-size: 10pt; font-family: 'Courier New', monospace;"
            " font-weight: bold; background: transparent;"
        )
        self.tempo_val_lbl.setFixedWidth(46)
        self.tempo_val_lbl.setAlignment(Qt.AlignCenter)
        tempo_ctrl.addWidget(self.tempo_val_lbl)

        reset_tempo = QPushButton("↺")
        reset_tempo.setFixedSize(26, 26)
        reset_tempo.setToolTip("Restablecer tempo a 100 %")
        reset_tempo.clicked.connect(lambda: self.tempo_slider.setValue(100))
        tempo_ctrl.addWidget(reset_tempo)

        tempo_lay.addLayout(tempo_ctrl)

        bottom_row.addWidget(tempo_frame, stretch=1)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("QFrame { background: #2a2a44; }")
        sep.setFixedWidth(1)
        bottom_row.addWidget(sep)

        # ── Loop A-B section ─────────────────────────────────────────
        loop_frame = QFrame()
        loop_frame.setStyleSheet(
            "QFrame { background: #161628; border-radius: 8px; }"
        )
        loop_lay = QVBoxLayout(loop_frame)
        loop_lay.setContentsMargins(10, 6, 10, 6)
        loop_lay.setSpacing(5)

        l_lbl = QLabel("LOOP A–B")
        l_lbl.setObjectName("sectionLabel")
        l_lbl.setAlignment(Qt.AlignCenter)
        loop_lay.addWidget(l_lbl)

        loop_ctrl = QHBoxLayout()
        loop_ctrl.setSpacing(5)

        self.loop_a_btn = QPushButton("▸ A")
        self.loop_a_btn.setFixedSize(42, 26)
        self.loop_a_btn.setToolTip("Marcar punto A (inicio del loop)  [A]")
        self.loop_a_btn.clicked.connect(self.set_loop_a_clicked)
        loop_ctrl.addWidget(self.loop_a_btn)

        self.loop_a_lbl = QLabel("--:--")
        self.loop_a_lbl.setStyleSheet(
            "color: #a89cff; font-size: 9pt; font-family: 'Courier New', monospace;"
            " font-weight: bold; background: transparent;"
        )
        self.loop_a_lbl.setMinimumWidth(40)
        self.loop_a_lbl.setAlignment(Qt.AlignCenter)
        loop_ctrl.addWidget(self.loop_a_lbl)

        arr = QLabel("→")
        arr.setStyleSheet("color: #404060; background: transparent;")
        loop_ctrl.addWidget(arr)

        self.loop_b_lbl = QLabel("--:--")
        self.loop_b_lbl.setStyleSheet(
            "color: #a89cff; font-size: 9pt; font-family: 'Courier New', monospace;"
            " font-weight: bold; background: transparent;"
        )
        self.loop_b_lbl.setMinimumWidth(40)
        self.loop_b_lbl.setAlignment(Qt.AlignCenter)
        loop_ctrl.addWidget(self.loop_b_lbl)

        self.loop_b_btn = QPushButton("B ◂")
        self.loop_b_btn.setFixedSize(42, 26)
        self.loop_b_btn.setToolTip("Marcar punto B (fin del loop)  [B]")
        self.loop_b_btn.clicked.connect(self.set_loop_b_clicked)
        loop_ctrl.addWidget(self.loop_b_btn)

        self.loop_clear_btn = QPushButton("✕")
        self.loop_clear_btn.setFixedSize(26, 26)
        self.loop_clear_btn.setToolTip("Limpiar loop  [L]")
        self.loop_clear_btn.setEnabled(False)
        self.loop_clear_btn.clicked.connect(self.clear_loop_clicked)
        loop_ctrl.addWidget(self.loop_clear_btn)

        self.loop_status_lbl = QLabel("Off")
        self.loop_status_lbl.setMinimumWidth(48)
        self.loop_status_lbl.setStyleSheet(
            "color: #505070; font-size: 8pt; background: transparent;"
        )
        self.loop_status_lbl.setAlignment(Qt.AlignCenter)
        loop_ctrl.addWidget(self.loop_status_lbl)

        loop_lay.addLayout(loop_ctrl)

        bottom_row.addWidget(loop_frame, stretch=2)

        root.addLayout(bottom_row)

        self.setStyleSheet(
            "TransportWidget { background: #111122; border-bottom: 1px solid #1e1e32; }"
        )

    # ── Internal slots ────────────────────────────────────────────────

    def _on_tempo_slider(self, value: int):
        self.tempo_val_lbl.setText(f"{value}%")
        self.tempo_changed.emit(value / 100.0)

    # ── Public API ────────────────────────────────────────────────────

    def set_playing(self, playing: bool):
        self._playing = playing
        self.play_btn.setText("⏸" if playing else "▶")

    def set_position(self, frac: float, current_sec: float, total_sec: float):
        self._total_sec = total_sec
        self.seek_bar.set_position(frac)
        self.time_label.setText(f"{_fmt(current_sec)} / {_fmt(total_sec)}")

    def set_song_title(self, title: str):
        self.song_title.setText(title)

    def update_loop_display(self,
                            a_sec: Optional[float],
                            b_sec: Optional[float],
                            frac_a: Optional[float],
                            frac_b: Optional[float]):
        """Update A-B labels, seek bar markers, and status indicator."""
        self.seek_bar.set_loop_markers(frac_a, frac_b)

        _lbl_base = (
            "color: #a89cff; font-size: 9pt; font-family: 'Courier New', monospace;"
            " font-weight: bold; background: transparent;"
        )

        if a_sec is not None:
            self.loop_a_lbl.setText(_fmt(a_sec))
            self.loop_a_btn.setStyleSheet(
                "QPushButton { background: #256840; color: #90ffb0; border-radius: 4px; }"
            )
        else:
            self.loop_a_lbl.setText("--:--")
            self.loop_a_btn.setStyleSheet("")
        self.loop_a_lbl.setStyleSheet(_lbl_base)

        if b_sec is not None:
            self.loop_b_lbl.setText(_fmt(b_sec))
            self.loop_b_btn.setStyleSheet(
                "QPushButton { background: #682525; color: #ffb0b0; border-radius: 4px; }"
            )
        else:
            self.loop_b_lbl.setText("--:--")
            self.loop_b_btn.setStyleSheet("")
        self.loop_b_lbl.setStyleSheet(_lbl_base)

        any_set = (a_sec is not None or b_sec is not None)
        active  = (a_sec is not None and b_sec is not None
                   and b_sec > a_sec)

        self.loop_clear_btn.setEnabled(any_set)
        if active:
            self.loop_status_lbl.setText("Activo")
            self.loop_status_lbl.setStyleSheet(
                "color: #50c878; font-size: 8pt; font-weight: bold;"
            )
        else:
            self.loop_status_lbl.setText("Off")
            self.loop_status_lbl.setStyleSheet("color: #505070; font-size: 8pt;")

    def reset(self):
        self.set_playing(False)
        self.seek_bar.set_position(0)
        self.time_label.setText("0:00 / 0:00")


def _fmt(sec: float) -> str:
    s = int(sec)
    return f"{s // 60}:{s % 60:02d}"
