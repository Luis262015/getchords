"""
Persistencia de proyectos de GetChords.

Dos formatos con el mismo contenido:
  · caché local   ~/.getchords/stems_cache/<md5>/   automático, indexado por contenido
  · bundle .gcs   un solo archivo portable          para mover entre equipos

Ambos guardan los stems en FLAC (sin pérdida, aprox. la mitad que WAV de 16 bits),
un manifest y los acordes ya detectados. Así, abrir un proyecto conocido no repite
ni la separación ni la detección de acordes.

La clave del caché es el MD5 del CONTENIDO del archivo de origen, no su ruta: el
mismo audio en otro equipo, otra carpeta u otro nombre resuelve al mismo proyecto.
Eso es lo que hace que la carpeta de caché sea copiable entre máquinas tal cual.

El manifest se escribe SIEMPRE al final. Su presencia es la marca de guardado
completo, de modo que una escritura interrumpida no deja un caché a medias que
luego se cargaría con stems faltantes.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import soundfile as sf


FORMAT_VERSION = 2
BUNDLE_EXT = '.gcs'

MANIFEST_NAME = 'manifest.json'
CHORDS_NAME = 'chords.json'
STEMS_DIR = 'stems'

_STEM_SUBTYPE = 'PCM_16'   # igual calidad que el caché WAV anterior, la mitad de tamaño


@dataclass
class ProjectData:
    """Un proyecto separado, ya sea del caché o de un bundle."""
    stems: Dict[str, np.ndarray]
    samplerate: int
    source_name: str = ''
    source_key: str = ''
    chords: List[dict] = field(default_factory=list)


def file_key(path: str) -> str:
    """MD5 del contenido del archivo. Identifica el proyecto entre equipos."""
    h = hashlib.md5()
    with open(path, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


# ── Lectura y escritura de stems ──────────────────────────────────────────────

def _write_stem(path: Path, audio: np.ndarray, samplerate: int):
    sf.write(str(path), audio, samplerate, format='FLAC', subtype=_STEM_SUBTYPE)


def _read_stem(source) -> tuple[np.ndarray, int]:
    audio, sr = sf.read(source, dtype='float32', always_2d=True)
    return audio, sr


def _build_manifest(source_name: str, source_key: str,
                    samplerate: int, stem_names: List[str]) -> dict:
    return {
        'format': FORMAT_VERSION,
        'app': 'GetChords Studio',
        'created': datetime.now().isoformat(timespec='seconds'),
        'source_name': source_name,
        'source_key': source_key,
        'samplerate': samplerate,
        'stems': list(stem_names),
    }


class ProjectStore:
    """
    Caché en disco de proyectos separados, más exportación e importación de
    bundles .gcs portables.
    """

    DEFAULT_ROOT = Path.home() / '.getchords' / 'stems_cache'

    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root is not None else self.DEFAULT_ROOT
        self.root.mkdir(parents=True, exist_ok=True)

    # ── Caché ─────────────────────────────────────────────────────────────

    def project_dir(self, key: str) -> Path:
        return self.root / key

    def has(self, key: str) -> bool:
        return self.load(key) is not None

    def load(self, key: str) -> Optional[ProjectData]:
        """
        Devuelve el proyecto cacheado, o None si no existe o está incompleto.
        Acepta también el caché antiguo de WAV sin manifest, para no perder el
        trabajo ya hecho en versiones anteriores.
        """
        folder = self.project_dir(key)
        if not folder.is_dir():
            return None

        manifest_path = folder / MANIFEST_NAME
        if manifest_path.exists():
            return self._load_v2(folder, manifest_path, key)
        return self._load_legacy(folder, key)

    def _load_v2(self, folder: Path, manifest_path: Path,
                 key: str) -> Optional[ProjectData]:
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        except Exception as exc:
            print(f"[ProjectStore] manifest ilegible en {folder.name}: {exc}")
            return None

        stems: Dict[str, np.ndarray] = {}
        samplerate = int(manifest.get('samplerate', 44100))

        # Todo stem listado en el manifest debe existir; si falta uno, el caché
        # quedó a medias y se descarta entero en vez de cargarlo incompleto.
        for name in manifest.get('stems', []):
            path = self._find_stem_file(folder, name)
            if path is None:
                print(f"[ProjectStore] falta el stem '{name}' en {folder.name}; se descarta el caché")
                return None
            try:
                audio, sr = _read_stem(str(path))
            except Exception as exc:
                print(f"[ProjectStore] no se pudo leer '{name}' en {folder.name}: {exc}")
                return None
            stems[name] = audio
            samplerate = sr

        if not stems:
            return None

        return ProjectData(
            stems=stems,
            samplerate=samplerate,
            source_name=manifest.get('source_name', ''),
            source_key=manifest.get('source_key', key),
            chords=self._read_chords(folder / CHORDS_NAME),
        )

    def _load_legacy(self, folder: Path, key: str) -> Optional[ProjectData]:
        """Caché de versiones anteriores: WAV sueltos, sin manifest ni acordes."""
        wavs = sorted(folder.glob('*.wav'))
        if not wavs:
            return None

        stems: Dict[str, np.ndarray] = {}
        samplerate = 44100
        for path in wavs:
            try:
                audio, sr = _read_stem(str(path))
            except Exception as exc:
                print(f"[ProjectStore] caché antiguo ilegible {path.name}: {exc}")
                return None
            stems[path.stem] = audio
            samplerate = sr

        return ProjectData(stems=stems, samplerate=samplerate, source_key=key)

    @staticmethod
    def _find_stem_file(folder: Path, name: str) -> Optional[Path]:
        for ext in ('.flac', '.wav'):
            path = folder / f'{name}{ext}'
            if path.exists():
                return path
        return None

    def save(self, key: str, stems: Dict[str, np.ndarray], samplerate: int,
             source_name: str = '') -> bool:
        """Guarda los stems en el caché. El manifest va al final, como marca de completo."""
        if not stems:
            return False

        folder = self.project_dir(key)
        try:
            # Una carpeta previa incompleta o en formato antiguo se reemplaza entera.
            if folder.exists():
                shutil.rmtree(folder, ignore_errors=True)
            folder.mkdir(parents=True, exist_ok=True)

            for name, audio in stems.items():
                _write_stem(folder / f'{name}.flac', audio, samplerate)

            manifest = _build_manifest(source_name, key, samplerate, list(stems))
            (folder / MANIFEST_NAME).write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8'
            )
            return True
        except Exception as exc:
            print(f"[ProjectStore] error al guardar el caché: {exc}")
            return False

    def save_chords(self, key: str, chords: List[dict]) -> bool:
        """Guarda los acordes junto a los stems ya cacheados."""
        folder = self.project_dir(key)
        if not folder.is_dir():
            return False
        try:
            (folder / CHORDS_NAME).write_text(
                json.dumps(chords, indent=2, ensure_ascii=False), encoding='utf-8'
            )
            return True
        except Exception as exc:
            print(f"[ProjectStore] error al guardar los acordes: {exc}")
            return False

    @staticmethod
    def _read_chords(path: Path) -> List[dict]:
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            return data if isinstance(data, list) else []
        except Exception as exc:
            print(f"[ProjectStore] acordes ilegibles: {exc}")
            return []

    def cache_size_bytes(self) -> int:
        return sum(f.stat().st_size for f in self.root.rglob('*') if f.is_file())

    # ── Bundles .gcs ──────────────────────────────────────────────────────

    @staticmethod
    def export_bundle(out_path: str, stems: Dict[str, np.ndarray], samplerate: int,
                      chords: Optional[List[dict]] = None,
                      source_name: str = '', source_key: str = '') -> None:
        """
        Escribe un .gcs: un ZIP con manifest, stems en FLAC y los acordes.

        Los FLAC ya vienen comprimidos, así que el ZIP los almacena sin volver a
        comprimir; solo los JSON se desinflan.
        """
        if not stems:
            raise ValueError("No hay stems que exportar.")

        manifest = _build_manifest(source_name, source_key, samplerate, list(stems))

        with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_STORED) as zf:
            zf.writestr(MANIFEST_NAME,
                        json.dumps(manifest, indent=2, ensure_ascii=False),
                        zipfile.ZIP_DEFLATED)
            for name, audio in stems.items():
                buf = io.BytesIO()
                sf.write(buf, audio, samplerate, format='FLAC', subtype=_STEM_SUBTYPE)
                zf.writestr(f'{STEMS_DIR}/{name}.flac', buf.getvalue())
            if chords:
                zf.writestr(CHORDS_NAME,
                            json.dumps(chords, indent=2, ensure_ascii=False),
                            zipfile.ZIP_DEFLATED)

    @staticmethod
    def import_bundle(path: str) -> ProjectData:
        """Lee un .gcs y devuelve su contenido listo para usar."""
        with zipfile.ZipFile(path, 'r') as zf:
            names = set(zf.namelist())
            if MANIFEST_NAME not in names:
                raise ValueError("El archivo no es un proyecto de GetChords válido "
                                 "(falta el manifest).")

            manifest = json.loads(zf.read(MANIFEST_NAME).decode('utf-8'))
            samplerate = int(manifest.get('samplerate', 44100))

            stems: Dict[str, np.ndarray] = {}
            for name in manifest.get('stems', []):
                entry = f'{STEMS_DIR}/{name}.flac'
                if entry not in names:
                    raise ValueError(f"El proyecto está incompleto: falta el stem '{name}'.")
                audio, sr = _read_stem(io.BytesIO(zf.read(entry)))
                stems[name] = audio
                samplerate = sr

            if not stems:
                raise ValueError("El proyecto no contiene stems.")

            chords: List[dict] = []
            if CHORDS_NAME in names:
                try:
                    data = json.loads(zf.read(CHORDS_NAME).decode('utf-8'))
                    chords = data if isinstance(data, list) else []
                except Exception:
                    pass

        return ProjectData(
            stems=stems,
            samplerate=samplerate,
            source_name=manifest.get('source_name', Path(path).stem),
            source_key=manifest.get('source_key', ''),
            chords=chords,
        )

    def import_bundle_to_cache(self, path: str) -> ProjectData:
        """Importa un .gcs y, si trae clave de origen, lo deja también en el caché."""
        data = self.import_bundle(path)
        if data.source_key:
            self.save(data.source_key, data.stems, data.samplerate, data.source_name)
            if data.chords:
                self.save_chords(data.source_key, data.chords)
        return data
