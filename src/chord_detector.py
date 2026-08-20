"""
Professional chord detection pipeline.

Layer 1 (best): madmom DeepChromaProcessor + CRFChordRecognitionProcessor
                CRNN trained on Billboard/RWC + HMM/CRF smoothing
Layer 2 (fallback): librosa CQT chroma + template matching + Viterbi HMM
                    Always available — uses already-installed librosa.

Output: list[ChordEvent] with timestamps, used for real-time display.
"""

from __future__ import annotations

import numpy as np
from dataclasses import asdict, dataclass

from PySide6.QtCore import QThread, Signal

try:
    import librosa
    LIBROSA_AVAILABLE = True
except ImportError:
    LIBROSA_AVAILABLE = False

try:
    from madmom.features.chords import DeepChromaProcessor, CRFChordRecognitionProcessor
    MADMOM_AVAILABLE = True
except ImportError:
    MADMOM_AVAILABLE = False


NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

# Suffix appended to root note for each quality
QUALITY_DISPLAY: dict[str, str] = {
    'maj':   '',
    'min':   'm',
    '7':     '7',
    'maj7':  'maj7',
    'min7':  'm7',
    'sus2':  'sus2',
    'sus4':  'sus4',
    'dim':   'dim',
    'aug':   'aug',
    'dim7':  'dim7',
    'hdim7': 'ø7',
}

# Accent color per quality for the display widget
QUALITY_COLOR: dict[str, str] = {
    'maj':   '#7c9ff7',
    'min':   '#a87cf7',
    '7':     '#7cf7c8',
    'maj7':  '#5cb8f5',
    'min7':  '#c87cf7',
    'sus2':  '#f7d07c',
    'sus4':  '#f7a87c',
    'dim':   '#f77c7c',
    'aug':   '#f5f07a',
    'dim7':  '#f77ca8',
    'hdim7': '#a8f77c',
}

# Interval profiles for each chord quality (12 pitch classes, root at index 0)
_QUALITY_PROFILES: dict[str, np.ndarray] = {
    'maj':   np.array([1,0,0,0,1,0,0,1,0,0,0,0], float),   # R  M3  P5
    'min':   np.array([1,0,0,1,0,0,0,1,0,0,0,0], float),   # R  m3  P5
    '7':     np.array([1,0,0,0,1,0,0,1,0,0,1,0], float),   # R  M3  P5  m7
    'maj7':  np.array([1,0,0,0,1,0,0,1,0,0,0,1], float),   # R  M3  P5  M7
    'min7':  np.array([1,0,0,1,0,0,0,1,0,0,1,0], float),   # R  m3  P5  m7
    'sus2':  np.array([1,0,1,0,0,0,0,1,0,0,0,0], float),   # R  M2  P5
    'sus4':  np.array([1,0,0,0,0,1,0,1,0,0,0,0], float),   # R  P4  P5
    'dim':   np.array([1,0,0,1,0,0,1,0,0,0,0,0], float),   # R  m3  d5
    'aug':   np.array([1,0,0,0,1,0,0,0,1,0,0,0], float),   # R  M3  A5
    'dim7':  np.array([1,0,0,1,0,0,1,0,0,1,0,0], float),   # R  m3  d5  d7
    'hdim7': np.array([1,0,0,1,0,0,1,0,0,0,1,0], float),   # R  m3  d5  m7
}

# Qualities the librosa backend is allowed to output. Restricted to the
# common, good-sounding chords of pop/rock so the chart is easy to play
# along to. Exotic qualities (dim, aug, sus, dim7, hdim7) win by tiny
# margins on noisy chroma and produce chords that sound wrong, so they
# are deliberately excluded here.
FUNDAMENTAL_QUALITIES: list[str] = ['maj', 'min', '7', 'min7', 'maj7']

# Mild preference for plain triads over their 7th extensions, so a simple
# C major isn't reported as Cmaj7 because of a single passing note.
_QUALITY_BIAS: dict[str, float] = {
    'maj': 1.00, 'min': 1.00, '7': 0.97, 'min7': 0.97, 'maj7': 0.97,
}

# Map any non-fundamental quality onto the nearest fundamental triad,
# used to simplify the madmom backend's richer output.
_SIMPLIFY_QUALITY: dict[str, str] = {
    'dim': 'min', 'dim7': 'min', 'hdim7': 'min',
    'aug': 'maj', 'sus2': 'maj', 'sus4': 'maj',
}


def _build_templates(qualities: list[str]) -> tuple[np.ndarray, list[tuple[str, str]], np.ndarray]:
    """Build L2-normalised templates for 12 roots × the given qualities."""
    templates: list[np.ndarray] = []
    labels: list[tuple[str, str]] = []
    bias: list[float] = []
    for quality in qualities:
        profile = _QUALITY_PROFILES[quality]
        for root in range(12):
            t = np.roll(profile, root).astype(np.float32)
            t /= np.linalg.norm(t) + 1e-8
            templates.append(t)
            labels.append((NOTE_NAMES[root], quality))
            bias.append(_QUALITY_BIAS.get(quality, 1.0))
    return (np.array(templates, dtype=np.float32),
            labels,
            np.array(bias, dtype=np.float32))


_TEMPLATES, _LABELS, _BIAS = _build_templates(FUNDAMENTAL_QUALITIES)


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class ChordEvent:
    start: float       # seconds
    end: float         # seconds
    chord: str         # display name, e.g. "Am7", "Fsus4"
    root: str          # pitch class, e.g. "A"
    quality: str       # quality key, e.g. "min7"
    confidence: float  # 0.0–1.0


def events_to_dicts(events: list[ChordEvent]) -> list[dict]:
    """Serializa acordes para guardarlos junto a los stems (JSON plano)."""
    return [asdict(ev) for ev in events]


def events_from_dicts(data: list[dict]) -> list[ChordEvent]:
    """
    Reconstruye acordes guardados. Ignora entradas corruptas en vez de fallar:
    un chords.json defectuoso debe degradar a "no hay acordes", no impedir que
    el proyecto se abra.
    """
    events: list[ChordEvent] = []
    for item in data:
        try:
            events.append(ChordEvent(
                start=float(item['start']),
                end=float(item['end']),
                chord=str(item['chord']),
                root=str(item['root']),
                quality=str(item['quality']),
                confidence=float(item.get('confidence', 0.0)),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return events


# ── Smoothing ─────────────────────────────────────────────────────────────────

def _mode_filter(labels: np.ndarray, window: int) -> np.ndarray:
    """
    Sliding-window majority vote over frame-level chord labels.

    Replaces Viterbi — avoids the tuning problem that comes from having
    132 states where the off-diagonal transition penalty is so large
    (log((1-s)/131)) that the model almost never changes state.

    labels : (T,)  int32 chord indices, -1 = silence
    window : odd int, number of frames in the sliding window
    returns: (T,)  smoothed labels
    """
    half = window // 2
    T = len(labels)
    result = np.empty(T, dtype=np.int32)
    for t in range(T):
        seg = labels[max(0, t - half): min(T, t + half + 1)]
        valid = seg[seg >= 0]
        if valid.size == 0:
            result[t] = -1
        else:
            result[t] = int(np.bincount(valid).argmax())
    return result


# ── librosa backend ───────────────────────────────────────────────────────────

def _detect_librosa(y_mono: np.ndarray, sr: int) -> list[ChordEvent]:
    """
    CQT chroma (36 bins/octave) → per-frame argmax → sliding-window
    majority vote → segmentation into ChordEvents.

    Operates on the pre-mixed harmonic stems (guitar + piano + other).
    HOP=2048 → ~93 ms/frame at 22050 Hz gives good chord-change resolution.
    """
    TARGET_SR = 22050
    HOP = 2048           # ~93 ms/frame — finer resolution than 4096
    SMOOTH_WIN = 15      # majority vote over ~1.4 s — stable, less flicker
    MIN_DUR = 1.0        # merge segments shorter than 1 s into neighbours
    SILENCE_RATIO = 0.02 # frames below 2 % of peak RMS = silence

    if sr != TARGET_SR:
        y_mono = librosa.resample(y_mono, orig_sr=sr, target_sr=TARGET_SR)
        sr = TARGET_SR

    total_sec = len(y_mono) / sr
    if total_sec < 0.5:
        return []

    # CQT-based chroma with 3× pitch resolution before folding to 12 semitones
    chroma = librosa.feature.chroma_cqt(
        y=y_mono, sr=sr, hop_length=HOP,
        bins_per_octave=36, norm=2,
    ).astype(np.float32)   # (12, T)

    # Per-frame RMS for silence detection
    rms = librosa.feature.rms(y=y_mono, hop_length=HOP)[0]   # (T,)
    peak = rms.max()
    if peak < 1e-7:
        return []
    silence_t = (rms < SILENCE_RATIO * peak)

    T = chroma.shape[1]
    hop_sec = HOP / sr

    # Cosine similarity: (T, 12) × (12, N) → (T, N)
    scores = (chroma.T @ _TEMPLATES.T).astype(np.float32)
    scores *= _BIAS   # nudge results toward plain triads over 7th chords

    # Per-frame argmax → raw chord index per frame
    frame_chords = np.argmax(scores, axis=1).astype(np.int32)   # (T,)
    frame_chords[silence_t[:T]] = -1   # mark silence frames

    # Majority-vote smoothing: reduces rapid flicker without over-suppressing changes
    smoothed = _mode_filter(frame_chords, SMOOTH_WIN)

    # Segment consecutive equal states into ChordEvents
    def _flush(start_f: int, end_f: int, state: int) -> ChordEvent | None:
        if state < 0:
            return None
        root, quality = _LABELS[state]
        chord_name = root + QUALITY_DISPLAY.get(quality, quality)
        conf = float(scores[start_f:end_f, state].mean())
        return ChordEvent(
            start=start_f * hop_sec,
            end=min(end_f * hop_sec, total_sec),
            chord=chord_name,
            root=root,
            quality=quality,
            confidence=min(conf, 1.0),
        )

    raw: list[ChordEvent] = []
    seg_start = 0
    prev = smoothed[0]
    for t in range(1, T + 1):
        cur = smoothed[t] if t < T else -2   # -2 flushes last segment
        if cur != prev:
            ev = _flush(seg_start, t, prev)
            if ev is not None:
                raw.append(ev)
            seg_start = t
            prev = cur

    return _postprocess(raw, MIN_DUR)


# ── Shared post-processing ──────────────────────────────────────────────────────

def _simplify(ev: ChordEvent) -> ChordEvent:
    """Collapse exotic qualities onto the nearest fundamental triad."""
    quality = _SIMPLIFY_QUALITY.get(ev.quality)
    if quality is None:
        return ev
    chord = ev.root + QUALITY_DISPLAY.get(quality, quality)
    return ChordEvent(ev.start, ev.end, chord, ev.root, quality, ev.confidence)


def _postprocess(events: list[ChordEvent], min_dur: float) -> list[ChordEvent]:
    """
    Make the chord chart easy to play along to:
      1. simplify exotic qualities to fundamental triads,
      2. merge consecutive identical chords,
      3. absorb segments shorter than `min_dur` into the previous chord.
    """
    out: list[ChordEvent] = []
    for ev in events:
        ev = _simplify(ev)
        if out and out[-1].root == ev.root and out[-1].quality == ev.quality:
            # Same chord as previous — extend it instead of repeating
            p = out[-1]
            out[-1] = ChordEvent(p.start, ev.end, p.chord, p.root, p.quality,
                                 max(p.confidence, ev.confidence))
        elif out and ev.end - ev.start < min_dur:
            # Too short to be musically meaningful — fold into previous
            p = out[-1]
            out[-1] = ChordEvent(p.start, ev.end, p.chord, p.root, p.quality, p.confidence)
        else:
            out.append(ev)
    return out


# ── madmom backend ────────────────────────────────────────────────────────────

_MADMOM_Q_MAP: dict[str, tuple[str, str]] = {
    'maj':   ('maj',   ''),
    'min':   ('min',   'm'),
    '7':     ('7',     '7'),
    'maj7':  ('maj7',  'maj7'),
    'min7':  ('min7',  'm7'),
    'sus2':  ('sus2',  'sus2'),
    'sus4':  ('sus4',  'sus4'),
    'dim':   ('dim',   'dim'),
    'aug':   ('aug',   'aug'),
    'dim7':  ('dim7',  'dim7'),
    'hdim7': ('hdim7', 'ø7'),
}


def _detect_madmom(audio_path: str) -> list[ChordEvent]:
    """
    madmom DeepChromaProcessor (CRNN) + CRFChordRecognitionProcessor (CRF+HMM).
    Analyzes the original full-mix file, which is what the model was trained on.
    """
    dcp = DeepChromaProcessor()
    crp = CRFChordRecognitionProcessor()
    chords = crp(dcp(audio_path))   # list of (start, end, label)

    events: list[ChordEvent] = []
    for start, end, label in chords:
        if label == 'N':
            continue
        if ':' in label:
            root, q_raw = label.split(':', 1)
            quality, display = _MADMOM_Q_MAP.get(q_raw, (q_raw, q_raw))
        else:
            root, quality, display = label, 'maj', ''
        events.append(ChordEvent(
            start=float(start),
            end=float(end),
            chord=root + display,
            root=root,
            quality=quality,
            confidence=0.92,
        ))
    return _postprocess(events, min_dur=1.0)


# ── QThread worker ────────────────────────────────────────────────────────────

class ChordDetectionWorker(QThread):
    """
    Background thread for chord detection.
    Tries madmom first (best quality), falls back to librosa+Viterbi.
    """
    progress = Signal(int, str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, stems: dict, samplerate: int,
                 audio_path: str | None = None, parent=None):
        super().__init__(parent)
        self._stems = stems
        self._sr = samplerate
        self._audio_path = audio_path

    def run(self):
        try:
            self.finished.emit(self._detect())
        except Exception as exc:
            self.error.emit(str(exc))

    def _detect(self) -> list[ChordEvent]:
        self.progress.emit(5, "Preparando stems armónicos…")

        # Prefer harmonic stems; fall back to everything except drums
        harmonic = [n for n in ('guitar', 'piano', 'other') if n in self._stems]
        if not harmonic:
            harmonic = [n for n in self._stems if n != 'drums']
        if not harmonic:
            raise RuntimeError("No hay stems armónicos disponibles.")

        # Mix to mono and peak-normalise
        parts = [self._stems[n].mean(axis=1) for n in harmonic]
        y_mix = np.mean(np.stack(parts, axis=0), axis=0).astype(np.float32)
        peak = float(np.abs(y_mix).max())
        if peak > 0:
            y_mix /= peak

        # Layer 1: madmom (uses original file for best accuracy)
        if MADMOM_AVAILABLE and self._audio_path:
            self.progress.emit(20, "Ejecutando madmom DeepChroma + CRF…")
            try:
                events = _detect_madmom(self._audio_path)
                self.progress.emit(100, "Detección madmom completada.")
                return events
            except Exception:
                pass  # fall through to librosa

        # Layer 2: librosa CQT chroma + Viterbi
        if not LIBROSA_AVAILABLE:
            raise RuntimeError("librosa no está instalado.")

        self.progress.emit(30, "Extrayendo chroma CQT…")
        self.progress.emit(50, "Aplicando Viterbi HMM…")
        events = _detect_librosa(y_mix, self._sr)
        self.progress.emit(100, "Detección completada.")
        return events


# ── High-level manager ────────────────────────────────────────────────────────

class ChordDetector:
    """Manages the detection worker and provides real-time chord lookup."""

    def __init__(self):
        self._worker: ChordDetectionWorker | None = None
        self._events: list[ChordEvent] = []

    def detect(self, stems: dict, samplerate: int, audio_path: str | None = None,
               on_progress=None, on_finished=None, on_error=None):
        if self._worker and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(2000)

        self._worker = ChordDetectionWorker(stems, samplerate, audio_path)
        if on_progress:
            self._worker.progress.connect(on_progress)
        if on_finished:
            self._worker.finished.connect(on_finished)
        if on_error:
            self._worker.error.connect(on_error)
        self._worker.start()

    @property
    def events(self) -> list[ChordEvent]:
        return self._events

    def set_events(self, events: list[ChordEvent]):
        self._events = events

    def chord_at(self, time_sec: float) -> ChordEvent | None:
        """Binary search — O(log n) lookup for real-time updates."""
        if not self._events:
            return None
        lo, hi = 0, len(self._events) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            ev = self._events[mid]
            if ev.end <= time_sec:
                lo = mid + 1
            elif ev.start > time_sec:
                hi = mid - 1
            else:
                return ev
        return None

    def clear(self):
        self._events = []

    def cancel(self):
        if self._worker and self._worker.isRunning():
            self._worker.quit()

    @staticmethod
    def is_available() -> bool:
        return LIBROSA_AVAILABLE
