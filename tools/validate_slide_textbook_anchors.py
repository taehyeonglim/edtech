#!/usr/bin/env python3
"""Validate textbook section deep links used in the revised lecture 1–3 decks.

Run ``python3 -m mkdocs build --strict`` first so the script can inspect the
actual IDs emitted by MkDocs rather than guessing a Korean heading slug.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
DECKS = tuple(
    f"chapters/chapter-{number:02d}/slides/deck.html" for number in range(1, 11)
)
TEXTBOOK_URL = re.compile(
    r"^/edtech/book/(?P<part>part[1-4])/(?P<chapter>ch\d{2})/$"
)


def deep_links(deck: Path) -> list[str]:
    text = deck.read_text(encoding="utf-8", errors="replace")
    return re.findall(r'href=["\']([^"\']+#[^"\']+)["\']', text, flags=re.IGNORECASE)


def validate(root: Path, built: Path) -> list[str]:
    errors: list[str] = []
    checked = 0
    for relative in DECKS:
        deck = root / relative
        if not deck.is_file():
            errors.append(f"missing deck: {relative}")
            continue
        links = [url for url in deep_links(deck) if "/edtech/book/" in url]
        if not links:
            errors.append(f"{relative}: no textbook section deep links found")
            continue
        for url in links:
            parsed = urlparse(url)
            match = TEXTBOOK_URL.fullmatch(parsed.path)
            fragment = unquote(parsed.fragment)
            if not match or not fragment:
                errors.append(f"{relative}: unsupported textbook deep link: {url}")
                continue
            output = built / match.group("part") / match.group("chapter") / "index.html"
            if not output.is_file():
                errors.append(f"{relative}: missing MkDocs output: {output}")
                continue
            count = output.read_text(encoding="utf-8", errors="replace").count(f'id="{fragment}"')
            checked += 1
            if count < 1:
                errors.append(f"{relative}: {url} -> id=\"{fragment}\" count={count}")
            else:
                print(f"PASS {relative}: #{fragment} (id count={count})")
    if not errors:
        print(f"Textbook deep-link anchor validation passed: {checked} link(s)")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root")
    parser.add_argument(
        "--built",
        type=Path,
        default=None,
        help="directory holding the built textbook (default: <root>/site)",
    )
    args = parser.parse_args()
    errors = validate(args.root, args.built or args.root / "site")
    if errors:
        print("Textbook deep-link anchor validation failed:", file=sys.stderr)
        print("\n".join(f"- {error}" for error in errors), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
