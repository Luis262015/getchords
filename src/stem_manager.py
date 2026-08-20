"""
Manages stem track data: in-memory storage, waveform peaks, and export.

La persistencia (caché en disco y bundles .gcs) vive en project_store.py: aquí
solo se decide qué proyecto está cargado, no cómo se guarda.
"""

import numpy as np
import soundfile as sf
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field

from src import mixing
from src.project_store import ProjectData, ProjectStore, file_key


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
    def __init__(self, store: Optional[ProjectStore] = None):
        self._store = store if store is not None else ProjectStore()
        self._stems: Dict[str, StemTrack] = {}
        self._source_key: Optional[str] = None
        self._source_name: str = ''
        self._cached_chords: List[dict] = []

    @property
    def store(self) -> ProjectStore:
        return self._store

    @property
    def source_key(self) -> Optional[str]:
        return self._source_key

    @property
    def cached_chords(self) -> List[dict]:
        """Acordes que venían con el proyecto cargado; vacío si hay que detectarlos."""
        return self._cached_chords

    # ── Loading ───────────────────────────────────────────────────────

    def load_from_separation(self, stems_dict: Dict[str, np.ndarray],
                             samplerate: int, source_file: str):
        """Import raw numpy arrays from AISeparator, normalise and cache."""
        self._set_stems(stems_dict, samplerate)
        self._cached_chords = []
        self._source_name = Path(source_file).name if source_file else ''

        try:
            self._source_key = file_key(source_file) if source_file else None
        except Exception as exc:
            print(f"[StemManager] no se pudo calcular la clave del origen: {exc}")
            self._source_key = None

        if self._source_key:
            self._store.save(self._source_key, self.get_stems_audio(),
                             samplerate, self._source_name)

    def load_from_cache(self, source_file: str) -> bool:
        """Returns True if a complete cached project was loaded."""
        try:
            key = file_key(source_file)
        except Exception as exc:
            print(f"[StemManager] no se pudo leer el archivo de origen: {exc}")
            return False

        data = self._store.load(key)
        if data is None:
            return False

        self.load_from_project(data)
        self._source_key = key
        self._source_name = data.source_name or Path(source_file).name
        return True

    def load_from_project(self, data: ProjectData):
        """Carga un proyecto ya materializado (caché o bundle .gcs importado)."""
        self._set_stems(data.stems, data.samplerate)
        self._source_key = data.source_key or None
        self._source_name = data.source_name
        self._cached_chords = list(data.chords)

    def save_chords(self, chords: List[dict]) -> bool:
        """Persiste los acordes detectados junto al proyecto en caché."""
        self._cached_chords = list(chords)
        if not self._source_key:
            return False
        return self._store.save_chords(self._source_key, chords)

    def export_bundle(self, out_path: str, chords: Optional[List[dict]] = None):
        """Escribe el proyecto completo como un archivo .gcs portable."""
        self._store.export_bundle(
            out_path,
            stems=self.get_stems_audio(),
            samplerate=self.get_samplerate(),
            chords=chords if chords is not None else self._cached_chords,
            source_name=self._source_name,
            source_key=self._source_key or '',
        )

    def _set_stems(self, stems_dict: Dict[str, np.ndarray], samplerate: int):
        self._stems.clear()
        for name, audio in stems_dict.items():
            self._stems[name] = StemTrack(
                name=name,
                audio=self._normalize_audio(audio),
                samplerate=samplerate,
            )

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

    def export_mix(self, output_path: str, mix_params: Dict[str, dict],
                   master_volume: float = 1.0):
        """
        Renderiza la mezcla a WAV con la MISMA ley que la reproduccion.

        `master_volume` debe recibir el valor del fader maestro: sin el, el
        archivo exportado sale con un nivel distinto del que se escucha.
        """
        if not self._stems:
            return
        sr = self.get_samplerate()
        total = self.get_total_frames()
        mixed = np.zeros((total, 2), dtype=np.float32)

        solo_active = mixing.any_soloed(mix_params)

        for name, stem in self._stems.items():
            params = mix_params.get(name, {})
            if not mixing.is_audible(params, solo_active):
                continue

            l_gain, r_gain = mixing.stem_gains(params)
            n = stem.num_frames
            mixed[:n, 0] += stem.audio[:, 0] * l_gain
            mixed[:n, 1] += stem.audio[:, 1] * r_gain

        if master_volume != 1.0:
            mixed *= float(master_volume)

        np.clip(mixed, -1.0, 1.0, out=mixed)
        sf.write(output_path, mixed, sr)

    @property
    def source_name(self) -> str:
        return self._source_name

    def clear(self):
        self._stems.clear()
        self._source_key = None
        self._source_name = ''
        self._cached_chords = []

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
