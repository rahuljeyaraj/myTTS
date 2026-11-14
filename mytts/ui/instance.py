"""One running copy per user. A later launch hands its request to that copy and exits.

A named mutex decides which process is first, without races. The first one
listens on a local socket (a named pipe on Windows); later launches connect
and send one JSON line such as {"cmd": "show"} or {"cmd": "open", "text": "..."}.
The first copy answers "ok" once it has read the line.
"""

from __future__ import annotations

import ctypes
import getpass
import hashlib
import json
import sys
import time

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

ERROR_ALREADY_EXISTS = 183
SYNCHRONIZE = 0x00100000
MAX_MESSAGE = 16 << 20  # bytes


def default_name() -> str:
    user = hashlib.sha1(getpass.getuser().lower().encode()).hexdigest()[:12]
    return f"mytts-{user}"


class SingleInstance(QObject):
    message = Signal(dict)

    def __init__(self, name: str | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self.name = name or default_name()
        self._mutex = None
        self._server: QLocalServer | None = None
        self._buffers: dict[QLocalSocket, bytes] = {}

    def acquire(self) -> bool:
        """True if this process is the first one; it then starts listening for messages."""
        if not self._take_mutex():
            return False
        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not server.listen(self.name):
            QLocalServer.removeServer(self.name)  # left over from a crash (Unix sockets only)
            server.listen(self.name)
        server.newConnection.connect(self._accept)
        self._server = server
        return True

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        if self._mutex:
            ctypes.windll.kernel32.CloseHandle(self._mutex)
            self._mutex = None

    def _take_mutex(self) -> bool:
        if sys.platform != "win32":
            return True  # Unix: the socket listen below decides (good enough off Windows)
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateMutexW.restype = ctypes.c_void_p
        k.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        k.CloseHandle.argtypes = [ctypes.c_void_p]
        h = k.CreateMutexW(None, False, f"Local\\{self.name}")
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            k.CloseHandle(h)
            return False
        self._mutex = h
        return bool(h)

    def _accept(self) -> None:
        while self._server is not None and (sock := self._server.nextPendingConnection()):
            self._buffers[sock] = b""
            sock.readyRead.connect(lambda s=sock: self._read(s))
            sock.disconnected.connect(lambda s=sock: self._drop(s))
            if sock.bytesAvailable():
                self._read(sock)

    def _read(self, sock: QLocalSocket) -> None:
        data = self._buffers.get(sock, b"") + bytes(sock.readAll().data())
        if b"\n" not in data:
            if len(data) > MAX_MESSAGE:
                sock.abort()
            else:
                self._buffers[sock] = data
            return
        line = data.split(b"\n", 1)[0]
        self._buffers[sock] = b""
        try:
            msg = json.loads(line.decode("utf-8"))
        except ValueError:
            msg = None
        if isinstance(msg, dict):
            sock.write(b"ok\n")
            sock.flush()
        sock.disconnectFromServer()  # sends what is still buffered first
        if isinstance(msg, dict):
            self.message.emit(msg)

    def _drop(self, sock: QLocalSocket) -> None:
        self._buffers.pop(sock, None)
        sock.deleteLater()


def is_running(name: str | None = None) -> bool:
    """True while some process holds the mutex, without taking it (Windows only)."""
    if sys.platform != "win32":
        return False
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenMutexW.restype = ctypes.c_void_p
    k.OpenMutexW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    h = k.OpenMutexW(SYNCHRONIZE, False, f"Local\\{name or default_name()}")
    if h:
        k.CloseHandle(h)
    return bool(h)


def wait_until_gone(name: str | None = None, timeout: float = 10.0) -> bool:
    """Wait for the running copy to release the mutex (it does that as it exits)."""
    deadline = time.monotonic() + timeout
    while is_running(name):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)
    return True


def send(message: dict, name: str | None = None, timeout: float = 3.0) -> bool:
    """Deliver `message` to the running copy. Retries while it is still starting up."""
    name = name or default_name()
    payload = json.dumps(message).encode("utf-8") + b"\n"
    deadline = time.monotonic() + timeout
    while True:
        sock = QLocalSocket()
        sock.connectToServer(name)
        if sock.waitForConnected(300):
            sock.write(payload)
            sock.flush()
            reply = b""
            while b"\n" not in reply and sock.waitForReadyRead(2000):
                reply += bytes(sock.readAll().data())
            sock.abort()
            return reply.startswith(b"ok")
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)
