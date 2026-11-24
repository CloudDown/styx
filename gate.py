"""Compatibility launcher for the original ``python -m styx.gate`` command."""

from .backend.gate import main

if __name__ == "__main__":
    raise SystemExit(main())
