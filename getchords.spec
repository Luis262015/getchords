# -*- mode: python ; coding: utf-8 -*-
"""
Especificación de PyInstaller para GetChords Studio.

Construir con:
    .venv\\Scripts\\python.exe -m PyInstaller getchords.spec --noconfirm
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

SPEC_DIR = Path(SPECPATH)
SITE = Path(sys.prefix) / 'Lib' / 'site-packages'

# Checkpoint de htdemucs_6s, tomado del caché de torch del sistema.
CHECKPOINT = '5c90dfd2-34c22ccb.th'
cache_root = os.environ.get('TORCH_HOME') or (Path.home() / '.cache' / 'torch')
checkpoint_src = Path(cache_root) / 'hub' / 'checkpoints' / CHECKPOINT
if not checkpoint_src.exists():
    raise SystemExit(
        f"Falta el modelo {CHECKPOINT} en {checkpoint_src}.\n"
        "Ejecuta la app una vez y separa un audio para descargarlo, o usa:\n"
        '  .venv\\Scripts\\python.exe -c "from demucs.pretrained import get_model; '
        'get_model(\'htdemucs_6s\')"'
    )

# ffmpeg empaquetado (decodifica M4A/AAC y otros formatos que libsndfile no cubre).
try:
    import imageio_ffmpeg
    ffmpeg_src = Path(imageio_ffmpeg.get_ffmpeg_exe())
except Exception:
    ffmpeg_src = None

datas = [
    (str(SITE / 'demucs' / 'remote'), 'demucs/remote'),
    # Colocado ya en el árbol que espera torch.hub: runtime_paths apunta
    # TORCH_HOME aquí y no hace falta copiar ni descargar nada.
    (str(checkpoint_src), 'torch_cache/hub/checkpoints'),
    (str(SITE / '_soundfile_data'), '_soundfile_data'),
    (str(SITE / '_sounddevice_data'), '_sounddevice_data'),
]
if ffmpeg_src and ffmpeg_src.exists():
    # PyInstaller conserva el nombre original (ffmpeg-win-x86_64-vX.Y.exe);
    # runtime_paths.ffmpeg_path() lo localiza con el patrón ffmpeg*.exe.
    datas.append((str(ffmpeg_src), 'ffmpeg'))

datas += collect_data_files('librosa')
datas += collect_data_files('sklearn')

hiddenimports = [
    'soundfile',
    'sounddevice',
    'omegaconf',
    'numba',
    'llvmlite',
    'sklearn.utils._typedefs',
    'sklearn.neighbors._partition_nodes',
    'scipy.special.cython_special',
]
hiddenimports += collect_submodules('demucs')
hiddenimports += collect_submodules('librosa')

# Qt: la app solo usa QtCore/QtGui/QtWidgets. Los "addons" pesan cientos de MB.
excludes = [
    'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick',
    'PySide6.QtWebView', 'PySide6.QtWebChannel', 'PySide6.QtWebSockets',
    'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuick3D', 'PySide6.QtQuickWidgets',
    'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets',
    'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.Qt3DInput',
    'PySide6.Qt3DLogic', 'PySide6.Qt3DAnimation', 'PySide6.Qt3DExtras',
    'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtDesigner',
    'PySide6.QtPdf', 'PySide6.QtPdfWidgets', 'PySide6.QtSql', 'PySide6.QtTest',
    'PySide6.QtBluetooth', 'PySide6.QtNfc', 'PySide6.QtSerialPort',
    'PySide6.QtPositioning', 'PySide6.QtLocation', 'PySide6.QtRemoteObjects',
    'PySide6.QtScxml', 'PySide6.QtSensors', 'PySide6.QtSpatialAudio',
    'PySide6.QtTextToSpeech', 'PySide6.QtHelp', 'PySide6.QtUiTools',
    # Herramientas de desarrollo que torch/otros arrastran sin necesidad en runtime.
    # NO excluir 'torchgen': pese al nombre, torch lo importa en runtime
    # (torchgen.code_template/model/utils). Excluirlo hacía que
    # `from demucs.pretrained import ...` lanzara ModuleNotFoundError y la app
    # mostrara "Demucs no está instalado".
    'torch.utils.tensorboard', 'torch.distributed.elastic',
    'matplotlib', 'tkinter', 'PIL', 'IPython', 'notebook', 'jupyter',
    'pytest', 'tensorboard', 'pandas',
    # El binario de ffmpeg ya se copia a datas bajo 'ffmpeg/'. Sin excluir el
    # paquete, PyInstaller recolecta además su copia interna: 83 MB duplicados.
    # En congelado ffmpeg_path() nunca lo importa (retorna antes).
    'imageio_ffmpeg',
]
# Nota: dora, openunmix y submitit NO se excluyen — demucs los importa al cargarse.


a = Analysis(
    ['main.py'],
    pathex=[str(SPEC_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GetChords Studio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='GetChords Studio',
)
