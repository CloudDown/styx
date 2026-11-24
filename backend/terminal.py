"""A real pseudo-terminal running Hermes' own TUI, for the browser terminal mode.

The browser only paints what this yields. The command is fixed (`hermes --tui`)
and never comes from the client: the gate exposes a terminal, not a shell.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import signal
import struct
import subprocess
import threading

try:  # POSIX only; the module still imports on Windows so the plugin loads.
    import fcntl
    import termios
except ImportError:  # pragma: no cover - Windows
    fcntl = termios = None

#: What the terminal runs. No argument, path or command is ever client-supplied.
ARGV = ("--tui",)


def command() -> list[str] | None:
    """The Hermes launcher, or None when this host has none.

    The gateway's PATH does not always carry the user's bin directory, so the
    two standard install locations are checked before giving up.
    """
    candidates = [shutil.which("hermes"),
                  os.path.expanduser("~/.local/bin/hermes"),
                  os.path.expanduser("~/.hermes/hermes-agent/.hermes/bin/hermes")]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return [candidate, *ARGV]
    return None


class Terminal:
    """One PTY child, read and written from the event loop (POSIX only)."""

    def __init__(self, argv: list[str], *, cwd: str | None = None, cols: int = 80,
                 rows: int = 24, env: dict[str, str] | None = None) -> None:
        if os.name != "posix" or fcntl is None or termios is None:
            raise OSError("pseudo-terminals need a POSIX host")
        self._loop = asyncio.get_running_loop()
        self._io_closed = False
        self._reaped = False
        self._out = bytearray()
        self._out_added = False
        self.reader: asyncio.Queue[bytes | None] = asyncio.Queue()

        master, slave = os.openpty()
        try:
            try:
                self._resize_fd(slave, cols, rows)
                proc = subprocess.Popen(
                    argv, stdin=slave, stdout=slave, stderr=slave, cwd=cwd,
                    env=env or os.environ.copy(), start_new_session=True, close_fds=True,
                )
            finally:
                os.close(slave)
        except BaseException:
            # Popen or the initial window-size ioctl failed: never leak the
            # master side of the pair or leave a half-created session behind.
            os.close(master)
            raise
        self._proc = proc
        self._fd = master
        try:
            os.set_blocking(master, False)
            self._loop.add_reader(master, self._readable)
        except BaseException:
            try:
                proc.kill()
            except OSError:
                pass
            os.close(master)
            raise

    @property
    def pid(self) -> int:
        return self._proc.pid

    @staticmethod
    def _resize_fd(fd: int, cols: int, rows: int) -> None:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def _readable(self) -> None:
        try:
            data = os.read(self._fd, 1 << 16)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            data = b""
        if data:
            self.reader.put_nowait(data)
        else:
            self._stop()

    def _writable(self) -> None:
        try:
            if self._out:
                written = os.write(self._fd, self._out)
                del self._out[:written]
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            self._out.clear()
        if not self._out and self._out_added:
            self._loop.remove_writer(self._fd)
            self._out_added = False

    def resize(self, cols: int, rows: int) -> None:
        """Clamp, not reject: a hidden tab can report a 0×0 viewport."""
        if self._io_closed:
            return
        try:
            self._resize_fd(self._fd, max(20, min(500, cols)), max(4, min(300, rows)))
        except OSError:
            pass

    def write(self, data: bytes) -> None:
        if self._io_closed or not data:
            return
        self._out += data
        if not self._out_added:
            self._loop.add_writer(self._fd, self._writable)
            self._out_added = True
        else:
            self._writable()

    def _stop(self) -> None:
        if self._io_closed:
            return
        self._io_closed = True
        try:
            self._loop.remove_reader(self._fd)
        except (OSError, ValueError):
            pass
        try:
            self._loop.remove_writer(self._fd)
        except (OSError, ValueError):
            pass
        self.reader.put_nowait(None)

    def close(self) -> None:
        """Hang up the session and reap it off the loop: closing a tab must never
        stall the gate because a child ignores SIGHUP."""
        if self._reaped:
            return
        self._stop()
        self._reaped = True
        try:
            os.killpg(self._proc.pid, signal.SIGHUP)
        except (OSError, ProcessLookupError):
            pass
        try:
            os.close(self._fd)
        except OSError:
            pass
        threading.Thread(target=self._reap, daemon=True).start()

    def _reap(self) -> None:
        try:
            self._proc.wait(timeout=1.5)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(self._proc.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
        try:
            self._proc.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            pass
