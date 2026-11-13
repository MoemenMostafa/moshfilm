"""Fast entry point for the Claude Code hooks: `python -m moshfilm.hook` (same as `moshfilm activity`).

It imports only the activity module (no pydantic, no CLI), reads a hook payload on stdin, and always exits 0.
"""
import json
import sys


def main() -> int:
    try:
        from . import activity

        activity.handle_hook(json.loads(sys.stdin.read()))
    except KeyboardInterrupt:
        raise
    except BaseException:  # even SystemExit: a hook must never get in Claude's way (exit 2 would block tools)
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
