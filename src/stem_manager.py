"""
Manages stem track data: storage, caching, waveform peaks, and export.
"""

import hashlib
import math
import numpy as np
import soundfile as sf
from pathlib import Path
from typing import Dict, Optional
from dataclasses import dataclass, field


STEM_COLORS: Dict[str, str] = {
    'vocals': '#ff6b9d',
    'drums':  '#ffa726',
    'bass':   '#ab47bc',
    'guitar': '#26c6da',
    'piano':  '#66bb6a',
    'other':  '#8d6e63',
}

STEM_LABELS: Dict[str, str] = {
    'vocals': 'Voces',
    'drums':  'Batería',
    'bass':   'Bajo',
    'guitar': 'Guitarra',
    'piano':  'Piano',
    'other':  'Otros',
}

STEM_ORDER = ['vocals', 'drums', 'bass', 'guitar', 'piano', 'other']


@dataclass
class StemTrack:
    name: str
    audio: np.ndarray      # (frames, 2) float32 stereo
    samplerate: int
    color: str = ''
    label: str = ''
    waveform_peaks: Optional[np.ndarray] = field(default=None, repr=False)

    def __post_init__(self):
        if not self.color:
            self.color = STEM_COLORS.get(self.name, '#7c6af7')
        if not self.label:
            self.label = STEM_LABELS.get(self.name, self.name.capitalize())
        if self.waveform_peaks is None:
            self._build_peaks()

    def _build_peaks(self, n_points: int = 1200):
        """Build min/max waveform envelope for drawing."""
        if len(self.audio) == 0:
            self.waveform_peaks = np.zeros((n_points, 2), dtype=np.float32)
            return
        mono = self.audio.mean(axis=1)
        frames = len(mono)
        chunk = max(1, frames // n_points)
        maxv, minv = [], []
        for i in range(0, frames, chunk):
            seg = mono[i: i + chunk]
            maxv.append(float(np.max(seg)))
            minv.append(float(np.min(seg)))
        self.waveform_peaks = np.column_stack([maxv, minv]).astype(np.float32)

    @property
    def duration(self) -> float:
        return len(self.audio) / self.samplerate

    @property
    def num_frames(self) -> int:
        return len(self.audio)


class StemManager:
    CACHE_DIR = Path.home() / '.getchords' / 'stems_cache'

    def __init__(self):
        self._stems: Dict[str, StemTrack] = {}
        self._source_hash: Optional[str] = None
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # ── Loading ───────────────────────────────────────────────────────

    def load_from_separation(self, stems_dict: Dict[str, np.ndarray],
                              samplerate: int, source_file: str):
        """Import raw numpy arrays from AISeparator, normalise and cache."""
        self._stems.clear()

        for name, audio in stems_dict.items():
            audio = self._normalize_audio(audio)
            stem = StemTrack(
                name=name,
                audio=audio,
                samplerate=samplerate,
            )
            self._stems[name] = stem

        try:
            self._source_hash = self._file_hash(source_file)
            self._write_cache()
        except Exception as e:
            print(f"[StemManager] Cache write error: {e}")

    def load_from_cache(self, source_file: str) -> bool:
        """Returns True if cached stems were loaded successfully."""
        try:
            key = self._file_hash(source_file)
            cache_dir = self.CACHE_DIR / key
            if not cache_dir.exists():
                return False

            wav_files = list(cache_dir.glob('*.wav'))
            if not wav_files:
                return False

            self._stems.clear()
            for wav_path in wav_files:
                audio, sr = sf.read(str(wav_path), dtype='float32', always_2d=True)
                name = wav_path.stem
                self._stems[name] = StemTrack(name=name, audio=audio, samplerate=sr)

            self._source_hash = key
            return True
        except Exception as e:
            print(f"[StemManager] Cache read error: {e}")
            return False

    # ── Accessors ─────────────────────────────────────────────────────

    def get_stem(self, name: str) -> Optional[StemTrack]:
        return self._stems.get(name)

    def get_all_stems(self) -> Dict[str, StemTrack]:
        return dict(self._stems)

    def get_stems_audio(self) -> Dict[str, np.ndarray]:
        return {n: s.audio for n, s in self._stems.items()}

    def stem_names(self):
        """Return names in preferred display order."""
        ordered = [n for n in STEM_ORDER if n in self._stems]
        extra = [n for n in self._stems if n not in STEM_ORDER]
        return ordered + extra

    def get_samplerate(self) -> int:
        if self._stems:
            return next(iter(self._stems.values())).samplerate
        return 44100

    def get_total_frames(self) -> int:
        if not self._stems:
            return 0
        return max(s.num_frames for s in self._stems.values())

    def is_loaded(self) -> bool:
        return bool(self._stems)

    # ── Export ────────────────────────────────────────────────────────

    def export_stem(self, name: str, output_path: str):
        stem = self._stems.get(name)
        if stem is None:
            raise ValueError(f"Stem '{name}' not found.")
        sf.write(output_path, stem.audio, stem.samplerate)

    def export_mix(self, output_path: str, mix_params: Dict[str, dict]):
        """Render mixed output to a WAV file."""
        if not self._stems:
            return
        sr = self.get_samplerate()
        total = self.get_total_frames()
        mixed = np.zeros((total, 2), dtype=np.float32)

        any_soloed = any(p.get('soloed', False) for p in mix_params.values())

        for name, stem in self._stems.items():
            params = mix_params.get(name, {})
            if params.get('muted', False):
                continue
            if any_soloed and not params.get('soloed', False):
                continue

            vol = float(params.get('volume', 1.0))
            pan = float(params.get('pan', 0.0))
            angle = (pan + 1.0) * (math.pi / 4.0)
            l_gain = vol * math.cos(angle)
            r_gain = vol * math.sin(angle)

            n = stem.num_frames
            mixed[:n, 0] += stem.audio[:, 0] * l_gain
            mixed[:n, 1] += stem.audio[:, 1] * r_gain

        np.clip(mixed, -1.0, 1.0, out=mixed)
        sf.write(output_path, mixed, sr)

    def clear(self):
        self._stems.clear()
        self._source_hash = None

    # ── Private ───────────────────────────────────────────────────────

    def _normalize_audio(self, audio: np.ndarray) -> np.ndarray:
        """Ensure (frames, 2) float32 layout."""
        if audio.ndim == 1:
            audio = np.stack([audio, audio], axis=1)
        elif audio.ndim == 2:
            if audio.shape[0] == 2 and audio.shape[1] != 2:
                audio = audio.T  # (channels, frames) → (frames, channels)
            if audio.shape[1] == 1:
                audio = np.concatenate([audio, audio], axis=1)
        return audio.astype(np.float32)

    def _write_cache(self):
        if not self._source_hash:
            return
        cache_dir = self.CACHE_DIR / self._source_hash
        cache_dir.mkdir(exist_ok=True)
        for name, stem in self._stems.items():
            sf.write(str(cache_dir / f'{name}.wav'), stem.audio, stem.samplerate)

    @staticmethod
    def _file_hash(path: str) -> str:
        h = hashlib.md5()
        with open(path, 'rb') as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
