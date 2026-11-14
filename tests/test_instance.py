import json
import subprocess
import sys
import uuid
from pathlib import Path

from conftest import wait_until
from mytts.ui.instance import SingleInstance, send

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
