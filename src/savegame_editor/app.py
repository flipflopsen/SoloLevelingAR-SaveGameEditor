"""qasync application bootstrap and predictable shutdown handling."""

from __future__ import annotations

import asyncio
import logging
import sys
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox
from qasync import QEventLoop

from savegame_editor.config import (
    EditorSettings,
    SettingsStore,
    SettingsStoreError,
    default_settings_path,
)
from savegame_editor.core.paths import application_root
from savegame_editor.services import SaveService
from savegame_editor.ui.main_window import MainWindow


def _configure_logging() -> None:
    try:
        log_path = default_settings_path().parent / "editor.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=log_path,
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
        )
    except OSError:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


async def _run_window(application: QApplication, window: MainWindow) -> None:
    closed = asyncio.Event()
    application.aboutToQuit.connect(closed.set)
    window.show()
    window.start()
    await closed.wait()


def run() -> int:
    """Create Qt and qasync, run the local application, then close its database worker."""
    _configure_logging()
    application = QApplication(sys.argv)
    application.setWindowIcon(QIcon(str(application_root() / "data" / "256x256.ico")))
    application.setOrganizationName("SaveGameEditor")
    application.setApplicationName("SaveGameEditor")
    settings_store = SettingsStore()
    try:
        settings = settings_store.load()
    except SettingsStoreError:
        logging.exception("Could not load local editor settings")
        settings = EditorSettings()
        QMessageBox.warning(
            None,
            "Settings unavailable",
            "Local settings could not be read; defaults were used.",
        )
    parser_path = application_root() / "vendor" / "gamedata.pyc"
    service = SaveService(parser_path)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="save-editor")
    loop = QEventLoop(application)
    asyncio.set_event_loop(loop)
    try:
        with loop:
            window = MainWindow(service, settings_store, settings, executor)
            loop.run_until_complete(_run_window(application, window))
            loop.run_until_complete(loop.run_in_executor(executor, service.close))
    except Exception:
        logging.exception("The editor stopped unexpectedly")
        QMessageBox.critical(
            None,
            "Editor error",
            "The editor stopped unexpectedly. Check the editor log for details.",
        )
        return 1
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return 0
