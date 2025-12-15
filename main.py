import sys
import signal
from PySide6.QtWidgets import QApplication, QSplashScreen
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon

from nt.gui import MainWindow


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon("assets/icon.png"))
    app.setApplicationName("Axonion")

    splash_pixmap = QPixmap("assets/splash.png")
    splash = QSplashScreen(
        splash_pixmap,
        Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint
    )
    splash.show()

    def start_main():
        window = MainWindow()
        window.resize(1200, 800)
        window.show()
        splash.finish(window)

    QTimer.singleShot(1200, start_main)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
