#!/usr/bin/env python3
"""Check a limited static accessibility baseline; this is not a WCAG conformance audit."""
from __future__ import annotations

import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".css", ".htm", ".html", ".markdown", ".md"}
MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.MULTILINE)
MARKDOWN_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
MARKDOWN_LINK = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)]*)\)")


class HtmlAudit(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.errors: list[str] = []
        self.lang_seen = False
        self.headings: list[tuple[int, int, str]] = []
        self.links: list[dict[str, object]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        line = self.getpos()[0]
        if tag == "html":
            self.lang_seen = bool((attributes.get("lang") or "").strip())
        elif tag == "img" and "alt" not in attributes:
            self.errors.append(f"line {line}: image is missing an alt attribute")
        elif tag == "a":
            href = (attributes.get("href") or "").strip()
            name = " ".join(filter(None, (attributes.get("aria-label"), attributes.get("title")))).strip()
            if not href:
                self.errors.append(f"line {line}: link has an empty href")
            self.links.append({"line": line, "name": name, "text": "", "depth": 1})
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.headings.append((int(tag[1]), line, ""))

        if self.links and tag != "a":
            self.links[-1]["depth"] = int(self.links[-1]["depth"]) + 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag != "a":
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.links:
            if tag == "a" and int(self.links[-1]["depth"]) == 1:
                link = self.links.pop()
                if not str(link["name"]).strip() and not str(link["text"]).strip():
                    self.errors.append(f"line {link['line']}: link has no accessible text")
            else:
                self.links[-1]["depth"] = int(self.links[-1]["depth"]) - 1
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and self.headings:
            level, line, text = self.headings[-1]
            if level == int(tag[1]) and not text.strip():
                self.errors.append(f"line {line}: heading is empty")

    def handle_data(self, data: str) -> None:
        if self.links:
            self.links[-1]["text"] = str(self.links[-1]["text"]) + data
        if self.headings:
            level, line, text = self.headings[-1]
            self.headings[-1] = (level, line, text + data)


def heading_errors(headings: list[tuple[int, int, str]]) -> list[str]:
    errors: list[str] = []
    if not any(level == 1 for level, _, _ in headings):
        errors.append("missing h1 heading")
    if sum(level == 1 for level, _, _ in headings) > 1:
        errors.append("document has more than one h1 heading")
    previous = 0
    for level, line, _ in headings:
        if previous and level > previous + 1:
            errors.append(f"line {line}: heading level skips from h{previous} to h{level}")
        previous = level
    return errors


def audit_html(text: str) -> list[str]:
    parser = HtmlAudit()
    parser.feed(text)
    parser.close()
    if not parser.lang_seen:
        parser.errors.append("html document is missing a non-empty lang attribute")
    parser.errors.extend(heading_errors(parser.headings))
    return parser.errors


def audit_markdown(text: str) -> list[str]:
    errors: list[str] = []
    headings = [(len(match.group(1)), text.count("\n", 0, match.start()) + 1, match.group(2)) for match in MARKDOWN_HEADING.finditer(text)]
    errors.extend(heading_errors(headings))
    for match in MARKDOWN_IMAGE.finditer(text):
        if not match.group(1).strip():
            errors.append(f"line {text.count(chr(10), 0, match.start()) + 1}: image has empty alt text")
    for match in MARKDOWN_LINK.finditer(text):
        if not match.group(1).strip() or not match.group(2).strip():
            errors.append(f"line {text.count(chr(10), 0, match.start()) + 1}: link is empty")
    return errors


def files_under(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if root.suffix.lower() in TEXT_SUFFIXES else []
    return sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES and ".git" not in path.parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--root", type=Path, default=ROOT, help="repository or candidate root")
    source.add_argument("--fixture", type=Path, help="fixture file or directory")
    args = parser.parse_args()
    root = (args.fixture or args.root).resolve()
    if not root.exists():
        print(f"Static accessibility validation failed:\n- source does not exist: {root}", file=sys.stderr)
        return 1
    errors: list[str] = []
    files = files_under(root)
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        audit = audit_html(text) if path.suffix.lower() in {".html", ".htm"} else audit_markdown(text) if path.suffix.lower() in {".md", ".markdown"} else []
        errors.extend(f"{path.relative_to(root) if root.is_dir() else path.name}: {error}" for error in audit)
    if errors:
        print("Static accessibility validation failed:", file=sys.stderr)
        print("\n".join(f"- {error}" for error in errors), file=sys.stderr)
        return 1
    print(f"Static accessibility validation passed: {len(files)} text file(s) checked; automated checks are not WCAG conformance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
