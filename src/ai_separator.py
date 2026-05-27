"""
AI-based audio source separation using Demucs / HTDemucs models.
Supports htdemucs_6s (6 stems) with fallback to htdemucs (4 stems).
GPU acceleration via CUDA with automatic CPU fallback.
"""

import math
import time
import threading
import numpy as np

from PySide6.QtCore import QThread, Signal

try:
    import torch
    import torchaudio
    from demucs.pretrained import get_model
    from demucs.apply import apply_model
    DEMUCS_AVAILABLE = True
except ImportError:
    DEMUCS_AVAILABLE = False

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
        finished(dict)      – {stem_name: np.ndarray (samples, 2)}  float32 stereo
        error(str)          – error message
    """

    progress = Signal(int, str)
    finished = Signal(dict)
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
            result = self._separate()
            if not self._cancelled:
                self.finished.emit(result)
        except Exception as exc:
            if not self._cancelled:
                self.error.emit(str(exc))

    # ── private ──────────────────────────────────────────────────────

    def _emit(self, pct: int, msg: str):
        if not self._cancelled:
            self.progress.emit(pct, msg)

    def _separate(self) -> dict:
        if not DEMUCS_AVAILABLE:
            raise RuntimeError(
                "Demucs no está instalado. Ejecuta:\n"
                "  pip install demucs torch torchaudio"
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
            return {}

        self._emit(90, "Convirtiendo resultados…")

        # ── 4. Extract stems ──────────────────────────────────────────
        sources = sources[0].cpu()  # (n_stems, channels, samples)
        result = {}
        for i, name in enumerate(model.sources):
            stem_tensor = sources[i]                   # (channels, samples)
            stem_np = stem_tensor.numpy().T.astype(np.float32)  # (samples, channels)
            result[name] = stem_np

        self._emit(100, "¡Separación completada!")
        return result

    def _load_audio(self, path: str):
        """Load audio file, return (tensor (channels, samples), sr)."""
        # Try torchaudio first (handles MP3, WAV, FLAC, M4A via ffmpeg backend)
        try:
            wav, sr = torchaudio.load(path)
            return wav, sr
        except Exception:
            pass

        # Fallback: soundfile (WAV, FLAC)
        if SOUNDFILE_AVAILABLE:
            try:
                data, sr = sf.read(path, dtype='float32', always_2d=True)
                wav = torch.tensor(data.T)  # (channels, samples)
                return wav, sr
            except Exception:
                pass

        raise RuntimeError(
            f"No se pudo leer el archivo: {path}\n"
            "Asegúrate de que ffmpeg esté instalado para MP3/M4A."
        )


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
