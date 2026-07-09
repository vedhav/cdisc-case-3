"""Run every tests/test_*.py, skipping (not failing) tests whose env is absent.

Usage:
    python tests/run_tests.py

Prints one pass/skip/fail line per test file and exits non-zero if any failed.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent


def load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    failed = 0
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        module = load(path)
        for name in sorted(n for n in dir(module) if n.startswith("test_")):
            fn = getattr(module, name)
            if not callable(fn):
                continue
            try:
                fn()
                print(f"PASS  {path.name}::{name}")
            except _Skip as exc:
                print(f"SKIP  {path.name}::{name} — {exc}")
            except Exception as exc:  # noqa: BLE001 — report any failure per test
                failed += 1
                print(f"FAIL  {path.name}::{name} — {type(exc).__name__}: {exc}")
    if failed:
        print(f"\n{failed} test(s) failed")
        return 1
    print("\nall tests passed (or skipped)")
    return 0


class _Skip(Exception):
    """Raise from a test to skip it when required env/secrets are absent."""


if __name__ == "__main__":
    sys.exit(main())
