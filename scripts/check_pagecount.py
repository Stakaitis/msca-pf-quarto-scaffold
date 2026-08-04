#!/usr/bin/env python3
"""Backwards-compatible shim: the page check is now a full compliance check.

This script used to count pages and nothing else, which is how a US Letter,
Latin Modern, footer-less PDF passed the build on 2026-07-28. The real checks
live in ``check_msca_compliance.py``; this file only translates the old
``<pdf> [limit]`` calling convention onto it, so every existing call site
(pixi tasks, Makefile targets, the Dockerfile CMD) gets the full check without
being rewritten.

Prefer calling the real checker directly in anything new:

    python scripts/check_msca_compliance.py _build/partB1.pdf --max-pages 10

Usage:
    python scripts/check_pagecount.py <pdf_path> [limit]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_msca_compliance import main  # noqa: E402


def main_shim(argv: list[str]) -> int:
    """Translate the legacy positional CLI onto the compliance checker.

    Args:
        argv: Command-line arguments excluding the program name; the first is
            the PDF path and the optional second is the page limit.

    Returns:
        Process exit code: 0 only if every hard compliance check passed.
    """
    if not argv:
        print("usage: check_pagecount.py <pdf_path> [limit]", file=sys.stderr)
        return 2
    limit = argv[1] if len(argv) > 1 else "10"
    return main([argv[0], "--max-pages", limit])


if __name__ == "__main__":
    raise SystemExit(main_shim(sys.argv[1:]))
