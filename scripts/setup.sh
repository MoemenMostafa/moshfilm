#!/usr/bin/env bash
# moshFilm setup: virtual environment, install, Chromium for export, ffmpeg check.
# Anything outside this folder (the `moshfilm` command on PATH, the Claude Code skill)
# is only written when you say yes: pass --path / --skill, or answer the question.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: scripts/setup.sh [options]

  --path       put `moshfilm` on PATH (symlink in ~/.local/bin) without asking
  --no-path    do not touch ~/.local/bin
  --skill      link the Claude Code skill into ~/.claude/skills/moshfilm without asking
  --no-skill   do not touch ~/.claude (also skips the PATH link unless --path is given)
  --yes        answer yes to both questions
  --dry-run    print what would happen and change nothing
  -h, --help   show this help

Without --path/--skill (or their --no- forms) the script asks, and when it is not
running in a terminal it skips those two steps and says so.
USAGE
}

want_path=ask
want_skill=ask
dry=0
for arg in "$@"; do
  case "$arg" in
    --path) want_path=yes ;;
    --no-path) want_path=no ;;
    --skill) want_skill=yes ;;
    --no-skill) want_skill=no; [ "$want_path" = ask ] && want_path=no ;;
    --yes) [ "$want_path" = ask ] && want_path=yes; [ "$want_skill" = ask ] && want_skill=yes ;;
    --dry-run) dry=1 ;;
    -h | --help) usage; exit 0 ;;
    *) echo "unknown option: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv="$root/.venv"

linked="Linked "
[ "$dry" = 1 ] && linked="Would link "

run() {
  if [ "$dry" = 1 ]; then
    echo "would run: $*"
  else
    "$@"
  fi
}

ask() { # ask "<question>" -> 0 for yes; no terminal means no
  [ -t 0 ] || return 1
  local reply
  read -r -p "$1 [y/N] " reply
  case "$reply" in [yY] | [yY][eE][sS]) return 0 ;; *) return 1 ;; esac
}

decide() { # decide <yes|no|ask> "<question>"
  case "$1" in
    yes) return 0 ;;
    no) return 1 ;;
    *) ask "$2" ;;
  esac
}

# 1. Python 3.11+ (found by name: the default python3 can be older)
python=""
for name in python3.13 python3.12 python3.11 python3; do
  if command -v "$name" >/dev/null 2>&1 &&
    "$name" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    python="$(command -v "$name")"
    break
  fi
done
if [ -z "$python" ]; then
  echo "moshFilm needs Python 3.11 or newer. Install one (macOS: brew install python@3.12) and run setup again." >&2
  exit 1
fi
echo "Using $python"

# 2. ffmpeg (checked early so a missing tool fails before the long install)
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "ffmpeg not found. Install it (macOS: brew install ffmpeg; Debian/Ubuntu: sudo apt install ffmpeg) and run setup again." >&2
  if [ "$dry" = 1 ]; then
    echo "(dry run: continuing)"
  else
    exit 1
  fi
fi

# 3. virtual environment and install (inside this folder)
if [ ! -x "$venv/bin/python" ] ||
  ! "$venv/bin/python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
  run "$python" -m venv "$venv"
fi
run "$venv/bin/python" -m pip install --quiet --upgrade pip
run "$venv/bin/python" -m pip install --quiet -e "$root"

# 4. Chromium for export (skipped when already downloaded)
chromium_present() {
  "$venv/bin/python" - <<'PY' 2>/dev/null
import os
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    raise SystemExit(0 if os.path.exists(p.chromium.executable_path) else 1)
PY
}
if [ "$dry" = 0 ] && chromium_present; then
  echo "Chromium already installed; skipping download."
else
  run "$venv/bin/playwright" install chromium
fi

# 5. `moshfilm` on PATH (outside this folder: only on request)
bin_dir="$HOME/.local/bin"
if decide "$want_path" "Link moshfilm into $bin_dir so Claude Code can run it?"; then
  link="$bin_dir/moshfilm"
  if [ -e "$link" ] && [ ! -L "$link" ]; then
    echo "$link exists and is not a link; left alone. Add $venv/bin to PATH instead."
  else
    run mkdir -p "$bin_dir"
    run ln -sfn "$venv/bin/moshfilm" "$link"
    echo "${linked}$link -> $venv/bin/moshfilm"
    case ":$PATH:" in
      *":$bin_dir:"*) ;;
      *) echo "$bin_dir is not on your PATH. Add this line to your shell profile:"
         # shellcheck disable=SC2016
         echo '  export PATH="$HOME/.local/bin:$PATH"' ;;
    esac
  fi
else
  echo "Skipped the PATH link. To use moshfilm without it, run $venv/bin/moshfilm."
fi

# 6. Claude Code skill (outside this folder: only on request)
skill_target="$HOME/.claude/skills/moshfilm"
if decide "$want_skill" "Link the Claude Code skill into $skill_target?"; then
  if [ -e "$skill_target" ] && [ ! -L "$skill_target" ]; then
    echo "$skill_target exists and is not a link; left alone."
  else
    run mkdir -p "$(dirname "$skill_target")"
    run ln -sfn "$root/skill/moshfilm" "$skill_target"
    echo "${linked}skill: $skill_target -> $root/skill/moshfilm"
  fi
else
  echo "Skipped the skill link. Link it later: ln -s $root/skill/moshfilm $skill_target"
fi

echo
echo "Try it: .venv/bin/moshfilm sample ~/moshfilm-sample && .venv/bin/moshfilm open ~/moshfilm-sample"
