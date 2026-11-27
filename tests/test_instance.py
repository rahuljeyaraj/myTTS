import inspect
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

from conftest import wait_until
from mytts.ui.app import quit_running
from mytts.ui.instance import SingleInstance, is_running, other_processes, send, wait_for_start, wait_until_gone

ROOT = Path(__file__).resolve().parent.parent

# A second launch is another process (Qt's blocking socket calls also need a Qt thread).
CLIENT = r"""
import json, sys
sys.path.insert(0, sys.argv[3])
from PySide6.QtCore import QCoreApplication
from mytts.ui.instance import send
app = QCoreApplication([])
if sys.argv[2] == "garbage":
    from PySide6.QtNetwork import QLocalSocket
    s = QLocalSocket(); s.connectToServer(sys.argv[1]); s.waitForConnected(1000)
    s.write(b"not json\n"); s.waitForBytesWritten(1000); s.waitForDisconnected(1000)
    sys.exit(0)
sys.exit(0 if send(json.loads(sys.argv[2]), sys.argv[1]) else 3)
"""


def unique_name():
    return f"mytts-test-{uuid.uuid4().hex[:10]}"


def client(tmp_path, name, payload):
    script = tmp_path / "client.py"
    script.write_text(CLIENT, encoding="utf-8")
    arg = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.Popen([sys.executable, str(script), name, arg, str(ROOT)])


def test_second_copy_hands_over_its_request(qapp, tmp_path):
    name = unique_name()
    first = SingleInstance(name)
    assert first.acquire()
    received = []
    first.message.connect(received.append)
    try:
        assert not SingleInstance(name).acquire()
        p = client(tmp_path, name, {"cmd": "open", "text": "Hello 📚"})
        assert wait_until(lambda: p.poll() is not None, 10_000)
        assert p.returncode == 0  # the running copy acknowledged it
        assert received == [{"cmd": "open", "text": "Hello 📚"}]
    finally:
        first.release()
    again = SingleInstance(name)
    assert again.acquire()  # free once the first copy is gone
    again.release()


def test_garbage_is_ignored(qapp, tmp_path):
    name = unique_name()
    first = SingleInstance(name)
    assert first.acquire()
    received = []
    first.message.connect(received.append)
    try:
        p = client(tmp_path, name, "garbage")
        assert wait_until(lambda: p.poll() is not None, 10_000)
        p = client(tmp_path, name, {"cmd": "show"})
        assert wait_until(lambda: p.poll() is not None, 10_000)
        assert p.returncode == 0
        assert received == [{"cmd": "show"}]
    finally:
        first.release()


def test_send_gives_up_without_a_running_copy(qapp):
    assert not send({"cmd": "show"}, unique_name(), timeout=0.2)


def test_is_running_follows_the_first_copy(qapp):
    name = unique_name()
    assert not is_running(name)
    first = SingleInstance(name)
    assert first.acquire()
    try:
        assert is_running(name)
        assert not wait_until_gone(name, timeout=0.1)
    finally:
        first.release()
    assert not is_running(name)
    assert wait_until_gone(name, timeout=0.1)


# A running copy that exits a moment after it is asked to.
SERVER = r"""
import sys
sys.path.insert(0, sys.argv[2])
import time
from PySide6.QtCore import QCoreApplication, QTimer
from mytts.ui.instance import SingleInstance
app = QCoreApplication([])
time.sleep(float(sys.argv[3]) if len(sys.argv) > 3 else 0)  # still starting up
instance = SingleInstance(sys.argv[1])
assert instance.acquire()
instance.message.connect(lambda m: m.get("cmd") == "quit" and QTimer.singleShot(300, app.quit))
app.aboutToQuit.connect(instance.release)
print("ready", flush=True)
app.exec()
"""


def test_quit_waits_until_the_running_copy_is_gone(qapp, tmp_path):
    name = unique_name()
    script = tmp_path / "server.py"
    script.write_text(SERVER, encoding="utf-8")
    p = subprocess.Popen([sys.executable, str(script), name, str(ROOT)], stdout=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline().strip() == "ready"
        start = time.monotonic()
        assert quit_running(timeout=10, name=name) == 0
        assert time.monotonic() - start >= 0.3  # it waited for the exit, not only the reply
        assert not is_running(name)
        p.wait(10)
    finally:
        p.kill()
    assert quit_running(timeout=1, name=name) == 1  # nothing left to quit


def test_other_processes_finds_a_copy_of_the_program():
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert p.pid in other_processes(sys.executable)
        assert p.pid not in other_processes(str(ROOT / "no-such.exe"))
    finally:
        p.kill()
        p.wait(10)


def test_wait_for_start_default_allows_a_slow_start():
    # After a silent update the new copy took up to 5 s to take the mutex (Windows Sandbox);
    # with a 5 s wait, an uninstall right after the update deleted the files under it.
    assert inspect.signature(wait_for_start).parameters["timeout"].default >= 20


def test_wait_for_start_waits_for_a_copy_that_is_starting(qapp, tmp_path):
    # As after a silent update: setup has just started the app when the uninstaller asks it to quit.
    name = unique_name()
    script = tmp_path / "server.py"
    script.write_text(SERVER, encoding="utf-8")
    assert not wait_for_start(None, name, timeout=5)  # no copy of the program: no waiting
    p = subprocess.Popen([sys.executable, str(script), name, str(ROOT), "1.5"], stdout=subprocess.PIPE, text=True)
    try:
        start = time.monotonic()
        assert wait_for_start(sys.executable, name, timeout=15)
        assert time.monotonic() - start >= 1.0
        assert p.stdout.readline().strip() == "ready"
        assert send({"cmd": "quit"}, name)
        p.wait(10)
    finally:
        p.kill()
