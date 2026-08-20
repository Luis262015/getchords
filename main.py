import sys

from src.runtime_paths import configure_runtime, log_startup

# Debe ejecutarse antes de importar torch/demucs (fija TORCH_HOME y flags de OpenMP).
configure_runtime()

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from src.ui.main_window import MainWindow


def main():
    try:
        log_startup()
    except Exception:
        pass  # el diagnóstico nunca debe impedir que arranque la app

    app = QApplication(sys.argv)
    app.setApplicationName("GetChords Studio")
    app.setOrganizationName("GetChords")
    app.setAttribute(Qt.AA_UseHighDpiPixmaps)

    font = QFont("Segoe UI", 9)
    app.setFont(font)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
