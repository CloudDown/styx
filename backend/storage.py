"""Atomic private-file replacement for small durable state."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from .platform_support import IS_WINDOWS, private_dir


def write_private(path: Path, content: str | bytes) -> None:
    private_dir(path.parent)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(raw)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content.encode("utf-8") if isinstance(content, str) else content)
            stream.flush()
            os.fsync(stream.fileno())
        deadline = time.monotonic() + 1
        while True:
            try:
                tmp.replace(path)
                break
            except PermissionError:
                # Readers/antivirus can briefly hold the old file on Windows.
                if not IS_WINDOWS or time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)
    finally:
        tmp.unlink(missing_ok=True)
