"""
Main application window – DAW-style layout with mixer, waveforms, and transport.
"""

import os
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame, QFileDialog,
    QSplitter, QGroupBox, QMessageBox, QToolBar, QSizePolicy,
    QApplication
)
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QKeySequence, QDragEnterEvent, QDropEvent, QFont

from src.ai_separator import AISeparator, SUPPORTED_FORMATS
from src.stem_manager import StemManager
from src.playback_engine import PlaybackEngine
from src.chord_detector import ChordDetector, events_from_dicts, events_to_dicts
from src.project_store import BUNDLE_EXT

from .styles import DARK_STYLE
from .transport_widget import TransportWidget
from .channel_strip import ChannelStrip
from .waveform_widget import WaveformWidget
from .processing_dialog import ProcessingDialog
from .chord_display_widget import ChordDisplayWidget


class DropZone(QWidget):
    """Drag-and-drop landing zone shown before any file is loaded."""

    file_dropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._hover = False
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(12)

        icon = QLabel("🎵")
        icon.setStyleSheet("font-size: 56px;")
        icon.setAlignment(Qt.AlignCenter)
        lay.addWidget(icon)

        title = QLabel("Arrastra tu archivo de audio aquí")
        title.setStyleSheet("color: #a89cff; font-size: 14pt; font-weight: bold;")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)

        sub = QLabel("o haz clic en Abrir")
        sub.setStyleSheet("color: #606080; font-size: 10pt;")
        sub.setAlignment(Qt.AlignCenter)
        lay.addWidget(sub)

        fmts = QLabel("MP3 · WAV · FLAC · M4A · AAC · OGG")
        fmts.setStyleSheet(
            "color: #505070; font-size: 9pt; "
            "background: #1a1a2e; border-radius: 6px; padding: 5px 12px;"
        )
        fmts.setAlignment(Qt.AlignCenter)
        lay.addWidget(fmts)

        if not AISeparator.is_available():
            warn = QLabel(
                "⚠ No se pudo cargar el motor de separación.\n"
                f"{AISeparator.unavailable_reason() or 'motivo desconocido'}"
            )
            warn.setStyleSheet("color: #cc8040; font-size: 9pt; text-align: center;")
            warn.setAlignment(Qt.AlignCenter)
            warn.setWordWrap(True)
            lay.addWidget(warn)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            url = event.mimeData().urls()[0]
            ext = Path(url.toLocalFile()).suffix.lower()
            if ext in SUPPORTED_FORMATS or ext == BUNDLE_EXT:
                event.acceptProposedAction()
                self._hover = True
                self.update()
                return
        event.ignore()

    def dragLeaveEvent(self, event):
        self._hover = False
        self.update()

    def dropEvent(self, event: QDropEvent):
        self._hover = False
        self.update()
        url = event.mimeData().urls()[0]
        self.file_dropped.emit(url.toLocalFile())

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QColor, QPen
        p = QPainter(self)
        c = QColor('#5040b0' if self._hover else '#2a2a44')
        p.setPen(QPen(c, 2, Qt.DashLine))
        p.setBrush(QColor('#1a1a2e' if not self._hover else '#1e1a38'))
        p.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 16, 16)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GetChords Studio")
        self.setMinimumSize(900, 650)
        self.resize(1200, 780)
        self.setAcceptDrops(True)

        self.setStyleSheet(DARK_STYLE)

        # Core objects
        self._separator = AISeparator()
        self._stem_manager = StemManager()
        self._playback = PlaybackEngine()
        self._chord_detector = ChordDetector()
        self._current_file: Optional[str] = None
        self._proc_dialog: Optional[ProcessingDialog] = None

        # Channel strips
        self._strips: Dict[str, ChannelStrip] = {}
        self._waveforms: Dict[str, WaveformWidget] = {}

        # Build UI
        self._build_toolbar()
        self._build_central()

        # Timers
        self._vu_timer = QTimer(self)
        self._vu_timer.setInterval(16)   # ~60 fps for VU meters
        self._vu_timer.timeout.connect(self._update_vu)

        self._pos_timer = QTimer(self)
        self._pos_timer.setInterval(33)  # ~30 fps for transport position
        self._pos_timer.timeout.connect(self._update_position)

        self._playback.set_on_finished(self._on_playback_finished)

        # Keyboard shortcuts
        self._setup_shortcuts()

    # ── UI Construction ───────────────────────────────────────────────

    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setStyleSheet("""
            QToolBar {
                background: #0a0a14;
                border-bottom: 1px solid #1e1e32;
                spacing: 6px;
                padding: 4px 8px;
            }
        """)

        # Logo / title
        logo_lbl = QLabel("  ♪ GetChords Studio  ")
        logo_lbl.setStyleSheet(
            "color: #a89cff; font-size: 12pt; font-weight: bold; letter-spacing: 1px;"
        )
        tb.addWidget(logo_lbl)
        tb.addSeparator()

        # Open
        open_btn = QPushButton("📂  Abrir")
        open_btn.setToolTip("Abrir archivo de audio (Ctrl+O)")
        open_btn.clicked.connect(self._open_file_dialog)
        tb.addWidget(open_btn)

        # Separate
        self._sep_btn = QPushButton("⚡  Separar")
        self._sep_btn.setToolTip("Ejecutar separación IA con HTDemucs")
        self._sep_btn.setEnabled(False)
        self._sep_btn.clicked.connect(self._run_separation)
        tb.addWidget(self._sep_btn)

        tb.addSeparator()

        # Export stem
        self._export_stem_btn = QPushButton("💾  Exportar stem")
        self._export_stem_btn.setEnabled(False)
        self._export_stem_btn.setToolTip("Exportar stem seleccionado como WAV")
        self._export_stem_btn.clicked.connect(self._export_stems)
        tb.addWidget(self._export_stem_btn)

        # Export mix
        self._export_mix_btn = QPushButton("🎛  Exportar mezcla")
        self._export_mix_btn.setEnabled(False)
        self._export_mix_btn.setToolTip("Exportar mezcla final como WAV")
        self._export_mix_btn.clicked.connect(self._export_mix)
        tb.addWidget(self._export_mix_btn)

        tb.addSeparator()

        # Proyecto .gcs: un archivo con stems y acordes ya resueltos, portable
        # entre equipos sin repetir la separación.
        self._export_proj_btn = QPushButton("📦  Exportar proyecto")
        self._export_proj_btn.setEnabled(False)
        self._export_proj_btn.setToolTip(
            "Guardar stems y acordes en un archivo .gcs portable")
        self._export_proj_btn.clicked.connect(self._export_project)
        tb.addWidget(self._export_proj_btn)

        open_proj_btn = QPushButton("📥  Abrir proyecto")
        open_proj_btn.setToolTip("Abrir un archivo .gcs ya separado")
        open_proj_btn.clicked.connect(self._open_project_dialog)
        tb.addWidget(open_proj_btn)

        tb.addSeparator()

        # Chord detection
        self._chord_btn = QPushButton("🎵  Acordes")
        self._chord_btn.setToolTip("Detectar acordes con IA (se activa tras separar)")
        self._chord_btn.setEnabled(False)
        self._chord_btn.clicked.connect(self._run_chord_detection)
        tb.addWidget(self._chord_btn)

        tb.addSeparator()

        # Status label
        self._status_lbl = QLabel("Listo")
        self._status_lbl.setStyleSheet("color: #505070; font-size: 9pt;")
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        tb.addWidget(self._status_lbl)

        self.addToolBar(tb)

    def _build_central(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_lay = QVBoxLayout(central)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setSpacing(0)

        # Transport
        self._transport = TransportWidget()
        self._transport.play_pause_clicked.connect(self._on_play_pause)
        self._transport.stop_clicked.connect(self._on_stop)
        self._transport.seek_requested.connect(self._on_seek)
        self._transport.master_volume_changed.connect(self._on_master_volume)
        self._transport.tempo_changed.connect(self._on_tempo_changed)
        self._transport.set_loop_a_clicked.connect(self._on_set_loop_a)
        self._transport.set_loop_b_clicked.connect(self._on_set_loop_b)
        self._transport.clear_loop_clicked.connect(self._on_clear_loop)
        main_lay.addWidget(self._transport)

        # Chord display strip
        self._chord_display = ChordDisplayWidget()
        main_lay.addWidget(self._chord_display)

        # Splitter: mixer (top) | waveforms (bottom)
        splitter = QSplitter(Qt.Vertical)
        splitter.setHandleWidth(4)
        splitter.setStyleSheet("QSplitter::handle { background: #1a1a2e; }")

        # ── Mixer area ──────────────────────────────────────────────────
        self._mixer_scroll = QScrollArea()
        self._mixer_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._mixer_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._mixer_scroll.setWidgetResizable(True)
        self._mixer_scroll.setMinimumHeight(220)

        mixer_container = QWidget()
        mixer_container.setStyleSheet("background: #0e0e1a;")
        self._mixer_lay = QHBoxLayout(mixer_container)
        self._mixer_lay.setContentsMargins(8, 8, 8, 8)
        self._mixer_lay.setSpacing(6)
        self._mixer_lay.setAlignment(Qt.AlignLeft)

        # Drop zone shown initially
        self._drop_zone = DropZone()
        self._drop_zone.file_dropped.connect(self._on_file_dropped)
        self._drop_zone.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._mixer_lay.addWidget(self._drop_zone)

        self._mixer_scroll.setWidget(mixer_container)
        splitter.addWidget(self._mixer_scroll)

        # ── Waveform area ───────────────────────────────────────────────
        wf_outer = QScrollArea()
        wf_outer.setWidgetResizable(True)
        wf_outer.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._wf_container = QWidget()
        self._wf_container.setStyleSheet("background: #0d0d1a;")
        self._wf_lay = QVBoxLayout(self._wf_container)
        self._wf_lay.setContentsMargins(4, 4, 4, 4)
        self._wf_lay.setSpacing(2)

        self._wf_placeholder = QLabel("Las formas de onda aparecerán aquí tras la separación.")
        self._wf_placeholder.setStyleSheet("color: #303050; font-size: 10pt;")
        self._wf_placeholder.setAlignment(Qt.AlignCenter)
        self._wf_lay.addWidget(self._wf_placeholder)

        wf_outer.setWidget(self._wf_container)
        splitter.addWidget(wf_outer)

        splitter.setSizes([240, 340])
        main_lay.addWidget(splitter, stretch=1)

    # ── Shortcut Setup ────────────────────────────────────────────────

    def _setup_shortcuts(self):
        from PySide6.QtGui import QShortcut
        QShortcut(QKeySequence("Space"),       self, self._on_play_pause)
        QShortcut(QKeySequence("S"),            self, self._on_stop)
        QShortcut(QKeySequence("Ctrl+O"),       self, self._open_file_dialog)
        QShortcut(QKeySequence("Right"),        self, lambda: self._seek_rel(5))
        QShortcut(QKeySequence("Left"),         self, lambda: self._seek_rel(-5))
        QShortcut(QKeySequence("A"),            self, self._on_set_loop_a)
        QShortcut(QKeySequence("B"),            self, self._on_set_loop_b)
        QShortcut(QKeySequence("L"),            self, self._on_clear_loop)

    def _seek_rel(self, delta_sec: float):
        cur = self._playback.position_seconds
        total = self._playback.duration_seconds
        self._on_seek(max(0.0, min(1.0, (cur + delta_sec) / max(total, 1.0))))

    # ── File Loading ──────────────────────────────────────────────────

    def _open_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Abrir archivo de audio",
            str(Path.home()),
            "Audio y proyectos (*.mp3 *.wav *.flac *.m4a *.aac *.ogg *.gcs);;"
            "Proyecto GetChords (*.gcs);;Todos (*)"
        )
        if path:
            self._load_file(path)

    def _on_file_dropped(self, path: str):
        self._load_file(path)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            self._load_file(urls[0].toLocalFile())

    def _load_file(self, path: str):
        # Un .gcs no se separa: ya viene resuelto.
        if Path(path).suffix.lower() == BUNDLE_EXT:
            self._open_project_file(path)
            return

        # Descargar el proyecto anterior ANTES de intentar el caché. Si no, un
        # fallo de caché dejaba cargados los stems de la canción previa: la app
        # seguía reproduciéndolos y además no llegaba nunca a guardar los nuevos.
        self._reset_project()

        self._current_file = path
        fname = Path(path).name
        self._transport.set_song_title(fname)
        self._set_status(f"Archivo cargado: {fname}")
        self._sep_btn.setEnabled(True)

        if self._stem_manager.load_from_cache(path):
            self._set_status(f"Stems cargados desde caché: {fname}")
            self._activate_project()
        else:
            self._run_separation()

    def _reset_project(self):
        """Deja la app sin proyecto cargado, lista para recibir otro."""
        self._on_stop()
        self._vu_timer.stop()
        self._pos_timer.stop()
        self._playback.load_stems({}, 44100)
        self._stem_manager.clear()
        self._chord_detector.clear()
        self._chord_display.clear()
        self._current_file = None
        self._export_stem_btn.setEnabled(False)
        self._export_mix_btn.setEnabled(False)
        self._export_proj_btn.setEnabled(False)
        self._chord_btn.setEnabled(False)
        self._sep_btn.setEnabled(False)

    # ── AI Separation ─────────────────────────────────────────────────

    def _run_separation(self):
        if not self._current_file:
            return

        self._on_stop()

        self._proc_dialog = ProcessingDialog(self)
        self._proc_dialog.cancelled.connect(self._on_separation_cancelled)
        self._proc_dialog.start_pulse()
        self._proc_dialog.show()

        self._separator.separate(
            self._current_file,
            on_progress=self._on_sep_progress,
            on_finished=self._on_separation_done,
            on_error=self._on_separation_error,
        )

    def _on_sep_progress(self, pct: int, msg: str):
        if self._proc_dialog:
            self._proc_dialog.update_progress(pct, msg)

    def _on_separation_done(self, stems_dict: dict, samplerate: int):
        if self._proc_dialog:
            self._proc_dialog.accept()
            self._proc_dialog = None

        if not stems_dict:
            return

        # Siempre se importa: el resultado recién separado es la fuente de verdad,
        # y es esta llamada la que escribe el caché en disco.
        self._stem_manager.load_from_separation(
            stems_dict, samplerate, self._current_file)
        self._set_status("Separación completada. ¡Listo para mezclar!")
        self._activate_project()

    def _activate_project(self):
        """
        Pone en marcha mezclador, ondas y reproducción para el proyecto ya
        cargado en el StemManager, venga de separación, caché o bundle .gcs.
        """
        stems_audio = self._stem_manager.get_stems_audio()
        if not stems_audio:
            return

        self._playback.load_stems(stems_audio, self._stem_manager.get_samplerate())
        self._rebuild_mixer()
        self._rebuild_waveforms()

        self._export_stem_btn.setEnabled(True)
        self._export_mix_btn.setEnabled(True)
        self._export_proj_btn.setEnabled(True)
        self._chord_btn.setEnabled(True)
        self._vu_timer.start()
        self._pos_timer.start()

        # Si el proyecto trae acordes guardados no se vuelve a analizar: esa era
        # la otra mitad del trabajo que se repetía en cada apertura.
        events = events_from_dicts(self._stem_manager.cached_chords)
        if events:
            self._chord_detector.set_events(events)
            self._set_status(
                f"Proyecto listo · {len(events)} acordes recuperados sin recalcular.")
        else:
            self._run_chord_detection()

    def _on_separation_error(self, msg: str):
        if self._proc_dialog:
            self._proc_dialog.reject()
            self._proc_dialog = None
        QMessageBox.critical(self, "Error de separación", msg)
        self._set_status("Error en la separación.")

    def _on_separation_cancelled(self):
        self._separator.cancel()
        self._set_status("Separación cancelada.")

    # ── Mixer Rebuild ─────────────────────────────────────────────────

    def _rebuild_mixer(self):
        # Clear old strips
        for strip in self._strips.values():
            strip.deleteLater()
        self._strips.clear()

        if self._drop_zone:
            self._drop_zone.hide()

        for name in self._stem_manager.stem_names():
            stem = self._stem_manager.get_stem(name)
            strip = ChannelStrip(name, stem.label, stem.color)
            strip.mute_changed.connect(self._on_mute)
            strip.solo_changed.connect(self._on_solo)
            strip.volume_changed.connect(self._on_volume)
            strip.pan_changed.connect(self._on_pan)
            self._strips[name] = strip
            self._mixer_lay.addWidget(strip)

        self._mixer_lay.addStretch()

    def _rebuild_waveforms(self):
        # Clear old waveforms
        for wf in self._waveforms.values():
            wf.deleteLater()
        self._waveforms.clear()

        self._wf_placeholder.hide()

        for name in self._stem_manager.stem_names():
            stem = self._stem_manager.get_stem(name)
            wf = WaveformWidget(name, stem.color)
            if stem.waveform_peaks is not None:
                wf.set_peaks(stem.waveform_peaks)
            wf.seek_requested.connect(self._on_seek)
            self._waveforms[name] = wf
            self._wf_lay.addWidget(wf)

        self._wf_lay.addStretch()

    # ── Playback Controls ─────────────────────────────────────────────

    def _on_play_pause(self):
        if not self._stem_manager.is_loaded():
            return
        if self._playback.playing:
            self._playback.pause()
            self._transport.set_playing(False)
        else:
            self._playback.play()
            self._transport.set_playing(True)

    def _on_stop(self):
        self._playback.stop()
        self._transport.set_playing(False)
        self._transport.set_position(0.0, 0.0, self._playback.duration_seconds)
        for wf in self._waveforms.values():
            wf.set_position(0.0)
        self._chord_display.clear()

    def _on_seek(self, frac: float):
        total = self._playback.total_frames
        frame = int(frac * total)
        was_playing = self._playback.playing
        self._playback.seek(frame)
        self._transport.set_playing(was_playing or self._playback.playing)

    def _on_master_volume(self, vol: float):
        self._playback.set_master_volume(vol)

    def _on_tempo_changed(self, speed: float):
        self._playback.set_speed(speed)

    def _on_set_loop_a(self):
        if not self._stem_manager.is_loaded():
            return
        self._playback.set_loop_a(self._playback.position)
        self._update_loop_display()

    def _on_set_loop_b(self):
        if not self._stem_manager.is_loaded():
            return
        self._playback.set_loop_b(self._playback.position)
        self._update_loop_display()

    def _on_clear_loop(self):
        self._playback.clear_loop()
        self._update_loop_display()

    def _update_loop_display(self):
        a_frame, b_frame = self._playback.loop_points
        total = self._playback.total_frames
        sr    = self._playback.samplerate

        a_sec  = a_frame / max(1, sr)    if a_frame is not None else None
        b_sec  = b_frame / max(1, sr)    if b_frame is not None else None
        frac_a = a_frame / max(1, total) if a_frame is not None else None
        frac_b = b_frame / max(1, total) if b_frame is not None else None

        self._transport.update_loop_display(a_sec, b_sec, frac_a, frac_b)

    def _on_playback_finished(self):
        # Called from audio thread — use invokeMethod to update UI safely
        from PySide6.QtCore import QMetaObject, Qt as QtNs
        QMetaObject.invokeMethod(self, "_playback_ended", QtNs.QueuedConnection)

    @Slot()
    def _playback_ended(self):
        self._transport.set_playing(False)
        self._transport.set_position(0.0, 0.0, self._playback.duration_seconds)

    # ── Chord Detection ───────────────────────────────────────────────

    def _run_chord_detection(self):
        if not self._stem_manager.is_loaded():
            return
        self._chord_btn.setEnabled(False)
        self._chord_display.clear()
        self._chord_detector.clear()
        self._chord_detector.detect(
            stems=self._stem_manager.get_stems_audio(),
            samplerate=self._stem_manager.get_samplerate(),
            audio_path=self._current_file,
            on_progress=self._on_chord_progress,
            on_finished=self._on_chord_done,
            on_error=self._on_chord_error,
        )

    def _on_chord_progress(self, pct: int, msg: str):
        self._set_status(f"Acordes: {msg}")

    def _on_chord_done(self, events: list):
        self._chord_detector.set_events(events)
        self._chord_btn.setEnabled(True)
        # Persistir junto a los stems para no repetir el análisis la próxima vez.
        self._stem_manager.save_chords(events_to_dicts(events))
        n = len(events)
        self._set_status(f"Acordes detectados: {n} segmento{'s' if n != 1 else ''}.")

    def _on_chord_error(self, msg: str):
        self._chord_btn.setEnabled(True)
        self._set_status(f"Error al detectar acordes: {msg}")

    # ── Mixer Param Changes ───────────────────────────────────────────

    def _on_mute(self, name: str, muted: bool):
        self._playback.set_param(name, 'muted', muted)

    def _on_solo(self, name: str, soloed: bool):
        self._playback.set_param(name, 'soloed', soloed)

    def _on_volume(self, name: str, vol: float):
        self._playback.set_param(name, 'volume', vol)

    def _on_pan(self, name: str, pan: float):
        self._playback.set_param(name, 'pan', pan)

    # ── Timer Callbacks ───────────────────────────────────────────────

    def _update_vu(self):
        for name, strip in self._strips.items():
            peaks = self._playback.peak_levels.get(name)
            if peaks is not None:
                strip.update_vu(float(peaks[0]), float(peaks[1]))

    def _update_position(self):
        if not self._stem_manager.is_loaded():
            return
        pos = self._playback.position_seconds
        total = self._playback.duration_seconds
        frac = pos / max(total, 0.001)

        self._transport.set_position(frac, pos, total)
        for wf in self._waveforms.values():
            wf.set_position(frac)

        self._chord_display.set_chord(self._chord_detector.chord_at(pos))

    # ── Export ────────────────────────────────────────────────────────

    def _export_stems(self):
        if not self._stem_manager.is_loaded():
            return
        export_dir = QFileDialog.getExistingDirectory(
            self, "Seleccionar carpeta de exportación", str(Path.home())
        )
        if not export_dir:
            return

        base = Path(self._current_file).stem if self._current_file else "stems"
        for name in self._stem_manager.stem_names():
            out = str(Path(export_dir) / f"{base}_{name}.wav")
            self._stem_manager.export_stem(name, out)

        QMessageBox.information(
            self, "Exportación completa",
            f"Stems exportados a:\n{export_dir}"
        )

    def _export_mix(self):
        if not self._stem_manager.is_loaded():
            return
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Exportar mezcla", str(Path.home() / "mezcla.wav"),
            "WAV (*.wav)"
        )
        if not out_path:
            return

        params = self._playback.get_all_params()
        # El maestro viaja aparte: no está en los parámetros por stem.
        self._stem_manager.export_mix(
            out_path, params, master_volume=self._playback.master_volume)
        QMessageBox.information(self, "Exportación completa", f"Mezcla guardada en:\n{out_path}")

    # ── Proyectos .gcs ────────────────────────────────────────

    def _export_project(self):
        """Guarda stems y acordes en un solo archivo portable entre equipos."""
        if not self._stem_manager.is_loaded():
            return

        base = self._stem_manager.source_name or (
            Path(self._current_file).name if self._current_file else "proyecto")
        suggested = str(Path.home() / (Path(base).stem + BUNDLE_EXT))

        out_path, _ = QFileDialog.getSaveFileName(
            self, "Exportar proyecto GetChords", suggested,
            f"Proyecto GetChords (*{BUNDLE_EXT})")
        if not out_path:
            return
        if not out_path.lower().endswith(BUNDLE_EXT):
            out_path += BUNDLE_EXT

        self._set_status("Exportando proyecto…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._stem_manager.export_bundle(
                out_path, events_to_dicts(self._chord_detector.events))
        except Exception as exc:
            QMessageBox.critical(self, "Error al exportar", str(exc))
            self._set_status("Error al exportar el proyecto.")
            return
        finally:
            QApplication.restoreOverrideCursor()

        size_mb = Path(out_path).stat().st_size / (1024 * 1024)
        self._set_status(f"Proyecto exportado ({size_mb:.0f} MB).")
        QMessageBox.information(
            self, "Proyecto exportado",
            f"Guardado en:\n{out_path}\n\n"
            f"Tamaño: {size_mb:.0f} MB\n\n"
            "Puedes abrir este archivo en otro equipo sin repetir la separación.")

    def _open_project_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Abrir proyecto GetChords", str(Path.home()),
            f"Proyecto GetChords (*{BUNDLE_EXT})")
        if path:
            self._open_project_file(path)

    def _open_project_file(self, path: str):
        """Carga un .gcs: ni separación ni detección de acordes."""
        self._reset_project()
        self._set_status("Abriendo proyecto…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            # Se deja también en el caché local, para que al abrir después el
            # audio original se reconozca por contenido y cargue igual de rápido.
            data = self._stem_manager.store.import_bundle_to_cache(path)
        except Exception as exc:
            QMessageBox.critical(self, "Error al abrir el proyecto", str(exc))
            self._set_status("No se pudo abrir el proyecto.")
            return
        finally:
            QApplication.restoreOverrideCursor()

        self._stem_manager.load_from_project(data)
        self._transport.set_song_title(data.source_name or Path(path).name)
        self._set_status(f"Proyecto abierto: {data.source_name or Path(path).name}")
        self._activate_project()

    # ── Helpers ───────────────────────────────────────────────────────

    def _set_status(self, msg: str):
        self._status_lbl.setText(msg)

    def closeEvent(self, event):
        self._playback.cleanup()
        super().closeEvent(event)
