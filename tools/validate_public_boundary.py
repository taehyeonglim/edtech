#!/usr/bin/env python3
"""Fail closed when public text contains private paths or sensitive evidence markers."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".css", ".htm", ".html", ".markdown", ".md"}
PRIVATE_PATH = re.compile(r"(?i)(?:^|[/\"'`()=:])/?(?:previous_lecture_content|content|docs-internal|\.gjc|site)(?:[/\\])")
LOCAL_URI = re.compile(r"(?i)\b(?:https?://(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?|file://)")
ROOT_PRIVATE_PATH = re.compile(r"(?i)(?:href|src|url)\s*[=(]\s*[\"']?/(?:previous_lecture_content|content|docs-internal|\.gjc|site)(?:[/\\]|\b)")
ROOT_ABSOLUTE_PATH = re.compile(r"(?i)(?:^|[\"'`()\s:=])(?:/Users/|/home/|[A-Z]:[\\/])")
SENSITIVE_MARKER = re.compile(
    r"(?i)(?:\braw[ _-]?evidence\b|\bstudent[ _-]?(?:id|name|email)\b|\blearner[ _-]?(?:id|name|email)\b|학번|학생\s*(?:이름|성명|이메일))"
)


def files_under(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if root.suffix.lower() in TEXT_SUFFIXES else []
    return sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES and ".git" not in path.parts)


def line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def audit(path: Path, text: str) -> list[str]:
    errors: list[str] = []
    checks = (
        (PRIVATE_PATH, "private/internal path marker"),
        (ROOT_PRIVATE_PATH, "root-absolute private/internal path"),
        (ROOT_ABSOLUTE_PATH, "root-absolute private/internal path"),
        (LOCAL_URI, "localhost or file URI"),
        (SENSITIVE_MARKER, "student-identifying or raw-evidence marker"),
    )
    for pattern, label in checks:
        for match in pattern.finditer(text):
            errors.append(f"line {line_number(text, match.start())}: {label}: {match.group(0).strip()}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--root", type=Path, default=ROOT, help="repository or candidate root")
    source.add_argument("--fixture", type=Path, help="fixture file or directory")
    args = parser.parse_args()
    root = (args.fixture or args.root).resolve()
    if not root.exists():
        print(f"Public-boundary validation failed:\n- source does not exist: {root}", file=sys.stderr)
        return 1
    errors: list[str] = []
    files = files_under(root)
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        display = path.relative_to(root) if root.is_dir() else path.name
        errors.extend(f"{display}: {error}" for error in audit(path, text))
    if errors:
        print("Public-boundary validation failed:", file=sys.stderr)
        print("\n".join(f"- {error}" for error in errors), file=sys.stderr)
        return 1
    print(f"Public-boundary validation passed: {len(files)} text file(s) checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
