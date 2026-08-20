"""
Resolución de rutas para ejecución normal y para el .exe congelado (PyInstaller).

Cuando PyInstaller congela la app, los recursos viven junto al ejecutable en vez
de junto al código fuente, y el caché de torch debe apuntar a una carpeta
escribible del usuario (el directorio de instalación puede ser de solo lectura).
"""

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "GetChordsStudio"

# Checkpoint de htdemucs_6s (6 stems). El nombre lo fija demucs/remote/htdemucs_6s.yaml.
BUNDLED_CHECKPOINT = "5c90dfd2-34c22ccb.th"


def is_frozen() -> bool:
    return getattr(sys, 'frozen', False)


def resource_path(relative: str) -> Path:
    """Ruta a un recurso empaquetado, válida en desarrollo y congelado."""
    if is_frozen():
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parent.parent
    return base / relative


def user_data_dir() -> Path:
    """Carpeta escribible por usuario para caché de modelos."""
    root = os.environ.get('LOCALAPPDATA') or Path.home() / '.cache'
    path = Path(root) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _bundled_torch_home() -> Path | None:
    """
    Caché de torch incluida en el bundle, ya con el checkpoint dentro.

    Se usa tal cual, sin copiar nada: torch.hub.load_state_dict_from_url solo
    descarga si el archivo no existe, y aquí existe. Basta permiso de lectura,
    así que funciona también instalado en Program Files.
    """
    root = resource_path('torch_cache')
    if (root / 'hub' / 'checkpoints' / BUNDLED_CHECKPOINT).exists():
        return root
    return None


def _install_bundled_model(torch_home: Path) -> bool:
    """Respaldo: copia el checkpoint al caché del usuario. True si quedó listo."""
    dest_dir = torch_home / 'hub' / 'checkpoints'
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / BUNDLED_CHECKPOINT

    if dest.exists() and dest.stat().st_size > 0:
        return True

    for candidate in (resource_path(f'torch_cache/hub/checkpoints/{BUNDLED_CHECKPOINT}'),
                      resource_path(f'models/{BUNDLED_CHECKPOINT}')):
        if candidate.exists():
            shutil.copy2(candidate, dest)
            return True
    return False


def ffmpeg_path() -> str | None:
    """Ruta al ffmpeg empaquetado, o None si no está disponible."""
    if is_frozen():
        # PyInstaller conserva el nombre original del binario (ffmpeg-win-x86_64-vX.Y.exe).
        folder = resource_path('ffmpeg')
        if folder.is_dir():
            for exe in sorted(folder.glob('ffmpeg*.exe')):
                return str(exe)
        return None

    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def configure_runtime() -> None:
    """
    Prepara el entorno antes de importar torch/demucs.
    Debe llamarse lo más pronto posible en el arranque.
    """
    # Conflicto habitual de OpenMP entre torch y otras libs en Windows: esta
    # variable evita el aborto por runtime duplicado y es la que hace falta.
    os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')

    # Hilos de cómputo para torch. Antes estaba fijado a 1, lo que dejaba la
    # separación en un solo núcleo y la volvía varias veces más lenta de lo
    # necesario en CPU. La mitad de los procesadores lógicos aproxima el número
    # de núcleos físicos, que es donde el cómputo denso deja de escalar.
    # Debe fijarse ANTES de importar torch: OpenMP lee la variable al inicializarse.
    os.environ.setdefault('OMP_NUM_THREADS', str(max(1, (os.cpu_count() or 2) // 2)))

    # En desarrollo se respeta el caché estándar de torch (~/.cache/torch), que ya
    # contiene el modelo.
    if not is_frozen():
        return

    # Modo portable: el checkpoint viaja dentro del bundle y se lee de ahí mismo.
    bundled = _bundled_torch_home()
    if bundled is not None:
        os.environ['TORCH_HOME'] = str(bundled)
        return

    # Respaldo si el bundle no trae el modelo: caché escribible del usuario.
    torch_home = user_data_dir() / 'torch'
    torch_home.mkdir(parents=True, exist_ok=True)
    os.environ['TORCH_HOME'] = str(torch_home)
    _install_bundled_model(torch_home)


def log_startup() -> Path:
    """
    Vuelca el estado del arranque a un archivo. El .exe se compila sin consola,
    así que sin esto un fallo de import es invisible.
    """
    from src import ai_separator as sep

    # En desarrollo TORCH_HOME no se fija y torch usa ~/.cache/torch; sin este
    # respaldo el log informaba "FALTA" con el checkpoint perfectamente presente.
    torch_home = os.environ.get('TORCH_HOME') or str(Path.home() / '.cache' / 'torch')
    checkpoint = Path(torch_home) / 'hub' / 'checkpoints' / BUNDLED_CHECKPOINT
    lines = [
        f"frozen        : {is_frozen()}",
        f"python        : {sys.version.split()[0]}",
        f"_MEIPASS      : {getattr(sys, '_MEIPASS', '(n/a)')}",
        f"TORCH_HOME    : {torch_home}",
        f"checkpoint    : {'OK' if checkpoint.exists() else 'FALTA'}  {checkpoint}",
        f"ffmpeg        : {ffmpeg_path() or 'no disponible'}",
        f"demucs        : {'OK' if sep.DEMUCS_AVAILABLE else 'FALLO'}",
        f"OMP_NUM_THREADS: {os.environ.get('OMP_NUM_THREADS', '(sin fijar)')}",
    ]

    # Sin consola en el .exe, este log es la unica via para saber si la
    # separacion esta corriendo en GPU o cayendo a CPU.
    if sep.DEMUCS_AVAILABLE:
        try:
            torch = sep.torch
            if torch.cuda.is_available():
                vram = torch.cuda.get_device_properties(0).total_memory / 1e9
                device = f"CUDA · {torch.cuda.get_device_name(0)} ({vram:.1f} GB)"
            else:
                device = f"CPU · {torch.get_num_threads()} hilos"
            lines.append(f"torch         : {torch.__version__}")
            lines.append(f"dispositivo   : {device}")
        except Exception as exc:
            lines.append(f"dispositivo   : indeterminado ({exc})")
    if not sep.DEMUCS_AVAILABLE:
        lines.append(f"motivo        : {sep.DEMUCS_IMPORT_ERROR}")

    path = user_data_dir() / 'startup.log'
    path.write_text("\n".join(lines) + "\n", encoding='utf-8')
    return path
