#!/usr/bin/env python3
"""Validate the public textbook-to-deck course-link contract without network access."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
TEXT_ONLY_CHAPTERS = {5, 8}
CHAPTERS = (
    (1, "part1/ch01.md", (1,)),
    (2, "part1/ch02.md", (2,)),
    (3, "part2/ch03.md", (4,)),
    (4, "part2/ch04.md", (5,)),
    (5, "part2/ch05.md", ()),
    (6, "part3/ch06.md", (6,)),
    (7, "part3/ch07.md", (7,)),
    (8, "part3/ch08.md", ()),
    (9, "part4/ch09.md", (8,)),
    (10, "part4/ch10.md", (3, 9)),
    (11, "part4/ch11.md", (9, 10)),
)
DECK_URL = re.compile(r"https://taehyeonglim\.github\.io/edtech/chapters/chapter-(\d{2})/slides/deck\.html")
FORBIDDEN_MARKER_PARTS = (
    ("/", "Users", "/"), ("file", "://"), ("Previous", "_lecture_content"),
    ("docs", "-internal"), ("content", "/chapters"), (".", "gjc", "/"),
    ("STATE", ".json"),
)


def marker_text(parts: tuple[str, ...]) -> str:
    return "".join(parts)


def check_portability(path: Path, text: str) -> list[str]:
    errors: list[str] = []
    for parts in FORBIDDEN_MARKER_PARTS:
        marker = marker_text(parts)
        if marker in text:
            errors.append(f"{path}: forbidden private or non-portable reference")
    for href in re.findall(r"(?:href|src)=[\"']([^\"']+)", text, flags=re.IGNORECASE):
        parsed = urlparse(href)
        if parsed.scheme == "file" or href.startswith("/Users/"):
            errors.append(f"{path}: forbidden filesystem link: {href}")
    return errors
def textbook_url(chapter: int) -> str:
    part = 1 if chapter <= 2 else 2 if chapter <= 5 else 3 if chapter <= 8 else 4
    return f"https://taehyeonglim.github.io/edtech/book/part{part}/ch{chapter:02d}/"



def check_root(root: Path) -> list[str]:
    errors: list[str] = []
    deck_owners: dict[int, set[int]] = {number: set() for number in range(1, 11)}
    for chapter, relative_doc, expected_decks in CHAPTERS:
        document = root / "docs" / relative_doc
        if not document.is_file():
            errors.append(f"missing textbook source: docs/{relative_doc}")
            continue
        text = document.read_text(encoding="utf-8", errors="replace")
        errors.extend(check_portability(document, text))
        found = {int(value) for value in DECK_URL.findall(text)}
        if chapter in TEXT_ONLY_CHAPTERS:
            if found:
                errors.append(f"docs/{relative_doc}: text-only chapter must not link to a deck")
        elif found != set(expected_decks):
            errors.append(
                f"docs/{relative_doc}: deck links must be {list(expected_decks)}, found {sorted(found)}"
            )
        for deck in found:
            if deck in deck_owners:
                deck_owners[deck].add(chapter)
            else:
                errors.append(f"docs/{relative_doc}: references unapproved deck {deck:02d}")

    for deck in range(1, 11):
        path = root / f"chapters/chapter-{deck:02d}/slides/deck.html"
        if not path.is_file():
            errors.append(f"missing public deck: chapters/chapter-{deck:02d}/slides/deck.html")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        errors.extend(check_portability(path, text))
        expected_backlinks = {textbook_url(chapter) for chapter in deck_owners[deck]}
        found_backlinks = {
            href
            for href in re.findall(r"href=[\"']([^\"']+)", text, flags=re.IGNORECASE)
            if href.startswith("https://taehyeonglim.github.io/edtech/book/")
        }
        if found_backlinks != expected_backlinks:
            errors.append(
                f"{path}: textbook backlinks must be {sorted(expected_backlinks)}, found {sorted(found_backlinks)}"
            )
        if not deck_owners[deck]:
            errors.append(f"deck {deck:02d} has no textbook link (round-trip mapping is incomplete)")

    if set(TEXT_ONLY_CHAPTERS) != {chapter for chapter, _, decks in CHAPTERS if not decks}:
        errors.append("text-only exception contract does not match the chapter mapping")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--root", type=Path, default=ROOT, help="repository or fixture root")
    source.add_argument("--fixture", type=Path, help="fixture root with docs/ and chapters/")
    args = parser.parse_args()
    root = args.fixture or args.root
    errors = check_root(root)
    if errors:
        print("Course-link validation failed:", file=sys.stderr)
        print("\n".join(f"- {error}" for error in errors), file=sys.stderr)
        return 1
    print("Course-link validation passed: 11 textbook chapters, 10 public decks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
