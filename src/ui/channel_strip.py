"""
Mixer channel strip: VU meter, volume fader, pan slider, mute/solo buttons.
One strip per stem.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSlider, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen

from .vu_meter import VUMeter


class ColorBar(QWidget):
    """Thin colour strip at top of channel."""
    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self.setFixedHeight(4)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), self._color)


class ChannelStrip(QWidget):
    """
    Signals:
        mute_changed(name, bool)
        solo_changed(name, bool)
        volume_changed(name, float)   – 0.0 to 1.5
        pan_changed(name, float)      – -1.0 to +1.0
    """

    mute_changed   = Signal(str, bool)
    solo_changed   = Signal(str, bool)
    volume_changed = Signal(str, float)
    pan_changed    = Signal(str, float)

    def __init__(self, stem_name: str, label: str, color: str, parent=None):
        super().__init__(parent)
        self._name = stem_name
        self._color = color
        self._muted = False
        self._soloed = False

        self.setFixedWidth(90)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        self._build_ui(label, color)

    def _build_ui(self, label: str, color: str):
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        # Colour accent bar
        root.addWidget(ColorBar(color))

        # Stem name
        name_lbl = QLabel(label)
        name_lbl.setAlignment(Qt.AlignCenter)
        name_lbl.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 9pt;")
        name_lbl.setMaximumHeight(18)
        root.addWidget(name_lbl)

        # VU meter (takes most vertical space)
        self.vu = VUMeter(self, Qt.Vertical)
        root.addWidget(self.vu, stretch=1)

        # Pan slider
        pan_row = QHBoxLayout()
        pan_row.setContentsMargins(0, 0, 0, 0)
        pan_lbl = QLabel("Pan")
        pan_lbl.setStyleSheet("color: #606080; font-size: 8pt;")
        pan_lbl.setAlignment(Qt.AlignCenter)
        pan_lbl.setMaximumHeight(14)
        root.addWidget(pan_lbl)

        self.pan_slider = QSlider(Qt.Horizontal)
        self.pan_slider.setRange(-100, 100)
        self.pan_slider.setValue(0)
        self.pan_slider.setTickPosition(QSlider.TicksBelow)
        self.pan_slider.setTickInterval(100)
        self.pan_slider.setMaximumHeight(20)
        self.pan_slider.setToolTip("Paneo estéreo")
        self.pan_slider.valueChanged.connect(self._on_pan)
        root.addWidget(self.pan_slider)

        # Volume fader
        vol_lbl = QLabel("Vol")
        vol_lbl.setStyleSheet("color: #606080; font-size: 8pt;")
        vol_lbl.setAlignment(Qt.AlignCenter)
        vol_lbl.setMaximumHeight(14)
        root.addWidget(vol_lbl)

        self.vol_slider = QSlider(Qt.Horizontal)
        self.vol_slider.setRange(0, 150)
        self.vol_slider.setValue(100)
        self.vol_slider.setMaximumHeight(20)
        self.vol_slider.setToolTip("Volumen (0 – 150%)")
        self.vol_slider.valueChanged.connect(self._on_volume)
        root.addWidget(self.vol_slider)

        # Volume value label
        self.vol_val = QLabel("100%")
        self.vol_val.setAlignment(Qt.AlignCenter)
        self.vol_val.setStyleSheet("color: #808090; font-size: 8pt;")
        self.vol_val.setMaximumHeight(14)
        root.addWidget(self.vol_val)

        # Mute / Solo buttons
        ms_row = QHBoxLayout()
        ms_row.setContentsMargins(0, 0, 0, 0)
        ms_row.setSpacing(3)

        self.mute_btn = QPushButton("M")
        self.mute_btn.setObjectName("muteBtn")
        self.mute_btn.setCheckable(True)
        self.mute_btn.setFixedSize(32, 22)
        self.mute_btn.setToolTip("Mute")
        self.mute_btn.clicked.connect(self._on_mute)
        ms_row.addWidget(self.mute_btn)

        self.solo_btn = QPushButton("S")
        self.solo_btn.setObjectName("soloBtn")
        self.solo_btn.setCheckable(True)
        self.solo_btn.setFixedSize(32, 22)
        self.solo_btn.setToolTip("Solo")
        self.solo_btn.clicked.connect(self._on_solo)
        ms_row.addWidget(self.solo_btn)

        root.addLayout(ms_row)

        # Thin frame border
        self.setStyleSheet(
            "ChannelStrip { background: #111122; border: 1px solid #1e1e32; border-radius: 6px; }"
        )

    # ── Slots ──────────────────────────────────────────────────────────

    def _on_mute(self, checked: bool):
        self._muted = checked
        self.mute_changed.emit(self._name, checked)

    def _on_solo(self, checked: bool):
        self._soloed = checked
        self.solo_changed.emit(self._name, checked)

    def _on_volume(self, value: int):
        fval = value / 100.0
        self.vol_val.setText(f"{value}%")
        self.volume_changed.emit(self._name, fval)

    def _on_pan(self, value: int):
        fval = value / 100.0
        self.pan_changed.emit(self._name, fval)

    # ── External updates ───────────────────────────────────────────────

    def update_vu(self, left: float, right: float):
        self.vu.set_levels(left, right)

    def set_muted_ext(self, muted: bool):
        """Reflect external mute state without re-emitting."""
        self._muted = muted
        self.mute_btn.setChecked(muted)

    def set_soloed_ext(self, soloed: bool):
        self._soloed = soloed
        self.solo_btn.setChecked(soloed)

    @property
    def name(self) -> str:
        return self._name
