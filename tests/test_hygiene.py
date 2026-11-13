import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", ".superpowers"}
SKIP_PREFIXES = ("src/moshfilm/static",)  # minified third-party bundle; docs/ IS scanned
# Reversed so the words do not appear literally in this file.
FORBIDDEN = [w[::-1] for w in ("air", "tenoruE", "kseDym", "relacsZ", "ppAenO")]
PATTERN = re.compile(r"\b(?:" + "|".join(map(re.escape, FORBIDDEN)) + r")\b", re.IGNORECASE)
# Personal and machine-specific strings, also reversed. Matched as plain substrings, any case.
LEAKS = [w[::-1] for w in ("ssob", "/sresU/", "pmt/etavirp/", "daphctarcs", "ed.yape", "tenorue")]
LEAK_PATTERN = re.compile("|".join(map(re.escape, LEAKS)), re.IGNORECASE)


def _repo_files():
    try:
        out = subprocess.run(
            ["git", "ls-files", "-co", "--exclude-standard"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.split("\n")
        paths = [ROOT / p for p in out if p]
    except (OSError, subprocess.CalledProcessError):
        paths = [p for p in ROOT.rglob("*") if p.is_file()]
    for p in paths:
        rel = p.relative_to(ROOT)
        if SKIP_DIRS & set(rel.parts) or rel.as_posix().startswith(SKIP_PREFIXES):
            continue
        if p.resolve() == Path(__file__).resolve() or not p.is_file():
            continue
        yield p


def test_no_forbidden_terms():
    hits = []
    for p in _repo_files():
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if PATTERN.search(text) or PATTERN.search(p.name) or LEAK_PATTERN.search(text):
            hits.append(str(p.relative_to(ROOT)))
    assert hits == []


def test_tls_never_disabled():
    banned = ("verify=False", "ssl=False", "CERT_NONE", "NODE_TLS_REJECT_UNAUTHORIZED")
    hits = []
    for sub in ("src", "scripts", "ui/src"):
        base = ROOT / sub
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or "node_modules" in p.parts or "static" in p.parts[len(ROOT.parts):]:
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            hits += [f"{p.relative_to(ROOT)}: {b}" for b in banned if b in text]
    assert hits == []
