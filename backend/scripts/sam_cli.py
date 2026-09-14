#!/usr/bin/env python3
"""SAMKY Studio CLI entry point.

The implementation remains in ``mirofish_cli`` so existing integrations keep working.
"""

from mirofish_cli import ApiError, main


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ApiError as exc:
        import sys

        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
