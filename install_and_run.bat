@echo off
echo ============================================================
echo  GetChords Studio - Instalacion y ejecucion
echo ============================================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python no encontrado. Instala Python 3.10+ desde python.org
    pause
    exit /b 1
)

echo [1/4] Instalando dependencias base...
pip install PySide6 sounddevice soundfile numpy scipy

echo.
echo [2/4] Instalando PyTorch (CPU + CUDA si disponible)...
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121

echo.
echo [3/4] Instalando Demucs...
pip install demucs

echo.
echo [4/4] Instalando librosa...
pip install librosa

echo.
echo ============================================================
echo  Instalacion completada. Iniciando GetChords Studio...
echo ============================================================
echo.
python main.py

pause
