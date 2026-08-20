"""
AI-based audio source separation using Demucs / HTDemucs models.
Supports htdemucs_6s (6 stems) with fallback to htdemucs (4 stems).
GPU acceleration via CUDA with automatic CPU fallback.
"""

import math
import os
import subprocess
import tempfile
import time
import threading
import numpy as np

from PySide6.QtCore import QThread, Signal

from src.runtime_paths import ffmpeg_path

try:
    import torch
    import torchaudio
    from demucs.pretrained import get_model
    from demucs.apply import apply_model
    DEMUCS_AVAILABLE = True
    DEMUCS_IMPORT_ERROR: str | None = None
except Exception as exc:
    # Se captura Exception y no solo ImportError: en el .exe congelado un fallo
    # de carga de DLL llega como OSError y antes tumbaba la app entera. El motivo
    # se conserva porque sin él "Demucs no está instalado" no es diagnosticable.
    DEMUCS_AVAILABLE = False
    DEMUCS_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

try:
    import soundfile as sf
    SOUNDFILE_AVAILABLE = True
except ImportError:
    SOUNDFILE_AVAILABLE = False


SUPPORTED_FORMATS = {'.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg', '.opus'}

PREFERRED_MODELS = ['htdemucs_6s', 'htdemucs']


class _FakeProgress(threading.Thread):
    """Emits smooth fake progress while demucs runs (no internal hook)."""

    def __init__(self, emit_fn, start_pct: int, end_pct: int, duration_est: float):
        super().__init__(daemon=True)
        self._fn = emit_fn           # renamed: avoids collision with Qt .emit()
        self._pct_start = start_pct
        self._pct_end = end_pct
        self._duration = max(duration_est, 10.0)
        self._cancel_flag = threading.Event()   # renamed: Thread._stop() is reserved

    def run(self):
        t0 = time.time()
        while not self._cancel_flag.wait(1.5):
            elapsed = time.time() - t0
            ratio = 1.0 - math.exp(-elapsed / (self._duration * 0.25))
            pct = int(self._pct_start + ratio * (self._pct_end - self._pct_start))
            self._fn(pct, f"Separando pistas con IA… {pct}%")

    def request_stop(self):
        self._cancel_flag.set()


class SeparationWorker(QThread):
    """
    Background thread that runs Demucs separation and emits Qt signals.
    Signals:
        progress(int, str)  – 0-100 percent + status message
        finished(dict, int) – {stem_name: np.ndarray (samples, 2)} float32 stereo,
                              más el samplerate real del modelo
        error(str)          – error message
    """

    progress = Signal(int, str)
    finished = Signal(dict, int)
    error = Signal(str)

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self._file_path = file_path
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        self.requestInterruption()

    def run(self):
        try:
            stems, samplerate = self._separate()
            if not self._cancelled:
                self.finished.emit(stems, samplerate)
        except Exception as exc:
            if not self._cancelled:
                self.error.emit(str(exc))

    # ── private ──────────────────────────────────────────────────────

    def _emit(self, pct: int, msg: str):
        if not self._cancelled:
            self.progress.emit(pct, msg)

    def _separate(self) -> tuple[dict, int]:
        if not DEMUCS_AVAILABLE:
            raise RuntimeError(
                f"No se pudo cargar Demucs.\n{DEMUCS_IMPORT_ERROR}"
            )

        # ── 1. Load model ─────────────────────────────────────────────
        self._emit(3, "Cargando modelo HTDemucs…")
        device = 'cuda' if torch.cuda.is_available() else 'cpu'

        model = None
        for model_name in PREFERRED_MODELS:
            try:
                self._emit(5, f"Descargando / cargando {model_name}…")
                model = get_model(model_name)
                break
            except Exception:
                continue

        if model is None:
            raise RuntimeError("No se pudo cargar ningún modelo Demucs.")

        model = model.to(device)
        model.eval()

        self._emit(12, f"Modelo cargado ({model_name}) · dispositivo: {device.upper()}")

        # ── 2. Load audio ─────────────────────────────────────────────
        self._emit(14, "Cargando archivo de audio…")
        wav, sr = self._load_audio(self._file_path)

        # Ensure stereo (2, samples)
        if wav.shape[0] == 1:
            wav = wav.repeat(2, 1)
        elif wav.shape[0] > 2:
            wav = wav[:2]

        # Resample to model's expected rate
        model_sr = model.samplerate
        if sr != model_sr:
            self._emit(16, f"Remuestreando {sr} Hz → {model_sr} Hz…")
            resampler = torchaudio.transforms.Resample(sr, model_sr)
            wav = resampler(wav)

        duration_sec = wav.shape[1] / model_sr
        self._emit(20, f"Audio listo: {duration_sec:.1f}s · {model_sr} Hz")

        # ── 3. AI separation ──────────────────────────────────────────
        # Estimate time: ~3s/min on GPU, ~30s/min on CPU (rough)
        time_est = duration_sec * (3 if device == 'cuda' else 30)
        fake_prog = _FakeProgress(self._emit, 20, 88, time_est)
        fake_prog.start()

        try:
            wav_device = wav.to(device)
            with torch.no_grad():
                sources = apply_model(
                    model,
                    wav_device[None],   # (1, channels, samples)
                    device=device,
                    shifts=1,
                    split=True,
                    overlap=0.25,
                    progress=False,
                    num_workers=0,
                )
        finally:
            fake_prog.request_stop()
            fake_prog.join(timeout=2)

        if self._cancelled:
            return {}, model_sr

        self._emit(90, "Convirtiendo resultados…")

        # ── 4. Extract stems ──────────────────────────────────────────
        sources = sources[0].cpu()  # (n_stems, channels, samples)
        result = {}
        for i, name in enumerate(model.sources):
            stem_tensor = sources[i]                   # (channels, samples)
            stem_np = stem_tensor.numpy().T.astype(np.float32)  # (samples, channels)
            result[name] = stem_np

        self._emit(100, "¡Separación completada!")
        # El samplerate viaja con los stems: apply_model devuelve audio a la tasa
        # del modelo, no a la del archivo original. Antes se asumía 44100 en la UI.
        return result, model_sr

    def _load_audio(self, path: str):
        """Load audio file, return (tensor (channels, samples), sr)."""
        # soundfile/libsndfile cubre WAV, FLAC, MP3 y OGG de forma nativa.
        if SOUNDFILE_AVAILABLE:
            try:
                data, sr = sf.read(path, dtype='float32', always_2d=True)
                return torch.tensor(data.T), sr  # (channels, samples)
            except Exception:
                pass

        # M4A/AAC y demás formatos exóticos: decodificar con ffmpeg a WAV temporal.
        try:
            return self._load_via_ffmpeg(path)
        except Exception as exc:
            raise RuntimeError(
                f"No se pudo leer el archivo: {path}\n{exc}"
            ) from exc

    def _load_via_ffmpeg(self, path: str):
        """Decodifica cualquier formato soportado por ffmpeg a float32 estéreo."""
        ffmpeg = ffmpeg_path()
        if not ffmpeg:
            raise RuntimeError("ffmpeg no disponible para decodificar este formato.")

        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'decoded.wav')
            proc = subprocess.run(
                [ffmpeg, '-nostdin', '-loglevel', 'error', '-y',
                 '-i', path, '-vn', '-f', 'wav', '-c:a', 'pcm_f32le', out],
                capture_output=True,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            if proc.returncode != 0 or not os.path.exists(out):
                raise RuntimeError(
                    proc.stderr.decode('utf-8', 'replace').strip() or
                    "ffmpeg no pudo decodificar el archivo."
                )
            data, sr = sf.read(out, dtype='float32', always_2d=True)
            return torch.tensor(data.T), sr


class AISeparator:
    """
    High-level manager for AI separation.
    Creates a SeparationWorker and wires it to caller callbacks.
    """

    def __init__(self):
        self._worker: SeparationWorker | None = None

    @staticmethod
    def is_available() -> bool:
        return DEMUCS_AVAILABLE

    @staticmethod
    def unavailable_reason() -> str | None:
        """Motivo real del fallo de import, o None si Demucs cargó bien."""
        return DEMUCS_IMPORT_ERROR

    @staticmethod
    def supported_formats() -> set:
        return SUPPORTED_FORMATS

    def separate(self, file_path: str,
                 on_progress=None, on_finished=None, on_error=None):
        """Start async separation. Callbacks receive (pct, msg), (dict), (str)."""
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)

        self._worker = SeparationWorker(file_path)

        if on_progress:
            self._worker.progress.connect(on_progress)
        if on_finished:
            self._worker.finished.connect(on_finished)
        if on_error:
            self._worker.error.connect(on_error)

        self._worker.start()

    def cancel(self):
        if self._worker:
            self._worker.cancel()
