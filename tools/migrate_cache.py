"""
Convierte el caché antiguo (WAV sueltos, sin manifest) al formato actual
(FLAC + manifest.json), sin pérdida de calidad y ocupando alrededor de un
tercio del espacio.

Uso:
    .venv\\Scripts\\python.exe tools\\migrate_cache.py            # convierte
    .venv\\Scripts\\python.exe tools\\migrate_cache.py --dry-run  # solo informa

La conversión es segura ante interrupciones: cada proyecto se escribe entero en
una carpeta aparte y se vuelve a leer para comprobarlo, y solo entonces se
sustituye el original. Si el proceso muere a mitad, el caché antiguo sigue ahí.
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.project_store import (  # noqa: E402
    MANIFEST_NAME, ProjectStore, _build_manifest, _write_stem,
)
import json  # noqa: E402


def folder_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob('*') if f.is_file())


def human(n: int) -> str:
    return f"{n / 1e6:.0f} MB" if n < 1e9 else f"{n / 1e9:.2f} GB"


def migrate_one(store: ProjectStore, folder: Path, dry_run: bool) -> tuple[int, int]:
    """Devuelve (bytes antes, bytes despues). (0, 0) si no habia nada que hacer."""
    key = folder.name

    if (folder / MANIFEST_NAME).exists():
        print(f"  {key[:12]}…  ya está en el formato actual, se omite")
        return (0, 0)

    before = folder_size(folder)

    data = store.load(key)          # lee el caché heredado a memoria
    if data is None:
        print(f"  {key[:12]}…  ILEGIBLE, se deja intacto")
        return (0, 0)

    stem_list = ", ".join(sorted(data.stems))
    print(f"  {key[:12]}…  {len(data.stems)} stems ({stem_list}) · {human(before)}")

    if dry_run:
        return (before, 0)

    # 1. Escribir la versión nueva en una carpeta aparte
    staging = folder.parent / (key + '.migrando')
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)

    try:
        for name, audio in data.stems.items():
            _write_stem(staging / f'{name}.flac', audio, data.samplerate)
        manifest = _build_manifest(data.source_name, key,
                                   data.samplerate, list(data.stems))
        (staging / MANIFEST_NAME).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')

        # 2. Releer lo escrito antes de tocar el original
        verify = ProjectStore(root=folder.parent)
        checked = verify._load_v2(staging, staging / MANIFEST_NAME, key)
        if checked is None or len(checked.stems) != len(data.stems):
            raise RuntimeError("la versión convertida no supera la verificación")
    except Exception as exc:
        shutil.rmtree(staging, ignore_errors=True)
        print(f"                 ERROR: {exc} — se conserva el original")
        return (0, 0)

    # 3. Sustituir
    after = folder_size(staging)
    shutil.rmtree(folder)
    os.rename(staging, folder)

    pct = 100 * after / before if before else 0
    print(f"                 -> {human(after)} ({pct:.0f} %)")
    return (before, after)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dry-run', action='store_true',
                    help="solo informa de lo que haria, sin escribir nada")
    ap.add_argument('--cache', type=Path, default=None,
                    help="carpeta de cache alternativa")
    args = ap.parse_args()

    store = ProjectStore(root=args.cache)
    print(f"Cache: {store.root}")

    folders = sorted(f for f in store.root.iterdir() if f.is_dir())
    if not folders:
        print("No hay proyectos en el cache.")
        return 0

    print(f"{len(folders)} proyecto(s) · {human(folder_size(store.root))} en total\n")

    total_before = total_after = 0
    converted = 0
    for folder in folders:
        before, after = migrate_one(store, folder, args.dry_run)
        if before:
            total_before += before
            total_after += after
            converted += 1

    print()
    if args.dry_run:
        print(f"{converted} proyecto(s) por convertir · {human(total_before)}. "
              "Ejecuta sin --dry-run para hacerlo.")
    elif converted:
        saved = total_before - total_after
        print(f"{converted} proyecto(s) convertidos: "
              f"{human(total_before)} -> {human(total_after)} "
              f"(liberados {human(saved)})")
    else:
        print("No habia nada que convertir.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
