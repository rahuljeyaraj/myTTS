import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    yield app


def wait_until(predicate, timeout_ms=2000):
    """Process Qt events until `predicate()` is true (PySide6 has no QTest.qWaitFor)."""
    import time

    from PySide6.QtTest import QTest

    end = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < end:
        if predicate():
            return True
        QTest.qWait(10)
    return bool(predicate())
