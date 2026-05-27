"""
Processing dialog shown while AI stem separation runs.
Shows animated progress bar, status text, and a cancel button.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton, QFrame
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont


class ProcessingDialog(QDialog):
    """
    Non-blocking modal dialog.
    Emits cancelled() when user clicks Cancel.
    """

    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Separando pistas")
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        self.setMinimumWidth(380)
        self._build_ui()

        # Pulse animation for indeterminate stage
        self._pulse_dir = 1
        self._pulse_val = 0
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(30)
        self._pulse_timer.timeout.connect(self._pulse)

    def _build_ui(self):
        self.setStyleSheet("""
            QDialog {
                background: #111126;
                border: 1px solid #3030a0;
                border-radius: 12px;
            }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(14)

        # Title
        title = QLabel("⚡  Separando con IA")
        title.setStyleSheet("color: #a89cff; font-size: 13pt; font-weight: bold;")
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)

        # Subtitle
        sub = QLabel("HTDemucs · Separación neural de pistas")
        sub.setStyleSheet("color: #606080; font-size: 9pt;")
        sub.setAlignment(Qt.AlignCenter)
        root.addWidget(sub)

        # Status text
        self.status_label = QLabel("Iniciando…")
        self.status_label.setStyleSheet("color: #c0c0e0; font-size: 10pt;")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background: #1a1a2e;
                border: none;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #5040b0, stop:1 #a89cff);
                border-radius: 4px;
            }
        """)
        root.addWidget(self.progress_bar)

        # Percentage label
        self.pct_label = QLabel("0%")
        self.pct_label.setStyleSheet("color: #8080b0; font-size: 9pt;")
        self.pct_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self.pct_label)

        # Info
        info = QLabel("El tiempo depende de la duración del audio y del hardware.")
        info.setStyleSheet("color: #404060; font-size: 8pt;")
        info.setAlignment(Qt.AlignCenter)
        info.setWordWrap(True)
        root.addWidget(info)

        # Cancel button
        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: 1px solid #404060;
                color: #808090;
                border-radius: 5px;
                padding: 6px 20px;
            }
            QPushButton:hover { border-color: #cc4040; color: #ff8080; }
        """)
        self.cancel_btn.clicked.connect(self._on_cancel)
        root.addWidget(self.cancel_btn, alignment=Qt.AlignCenter)

    def update_progress(self, pct: int, message: str):
        self.progress_bar.setValue(pct)
        self.pct_label.setText(f"{pct}%")
        self.status_label.setText(message)

        # Stop pulsing once we have real progress > 0
        if pct > 0 and self._pulse_timer.isActive():
            self._pulse_timer.stop()

    def start_pulse(self):
        """Animate indeterminate bar before first progress event."""
        self._pulse_timer.start()

    def _pulse(self):
        self._pulse_val += self._pulse_dir * 2
        if self._pulse_val >= 100:
            self._pulse_dir = -1
        elif self._pulse_val <= 0:
            self._pulse_dir = 1
        self.progress_bar.setValue(self._pulse_val)

    def _on_cancel(self):
        self.cancelled.emit()
        self.reject()

    def closeEvent(self, event):
        self.cancelled.emit()
        super().closeEvent(event)
