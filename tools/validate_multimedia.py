#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
# --- How to run ---
# python3 tools/validate_multimedia.py --help
# python3 tools/validate_multimedia.py --evidence-root /path/to/.omo/evidence/edtech-multimedia --all

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict


REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "media_id",
    "chapter",
    "placement",
    "type",
    "title",
    "creator_or_channel",
    "source_url",
    "embed_url_or_local_path",
    "license_or_terms",
    "verification_method",
    "verified_at",
    "caption_or_transcript_status",
    "alt_text_or_summary",
    "fallback",
    "public_use_ok",
    "status",
)
ALLOWED_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "verified-embed",
        "verified-link",
        "verified-local-original",
        "verified-oer-image",
        "omitted-unverified",
    }
)
CHAPTERS: Final[tuple[tuple[str, str], ...]] = (
    ("docs/part1/ch01.md", "ch01-media-ledger.md"),
    ("docs/part1/ch02.md", "ch02-media-ledger.md"),
    ("docs/part2/ch03.md", "ch03-media-ledger.md"),
    ("docs/part2/ch04.md", "ch04-media-ledger.md"),
    ("docs/part2/ch05.md", "ch05-media-ledger.md"),
    ("docs/part3/ch06.md", "ch06-media-ledger.md"),
    ("docs/part3/ch07.md", "ch07-media-ledger.md"),
    ("docs/part3/ch08.md", "ch08-media-ledger.md"),
    ("docs/part4/ch09.md", "ch09-media-ledger.md"),
    ("docs/part4/ch10.md", "ch10-media-ledger.md"),
    ("docs/part4/ch11.md", "ch11-media-ledger.md"),
)


class Args(TypedDict):
    evidence_root: Path
    all_chapters: bool
    chapter: Path | None
    ledger: str | None
    min_media: int
    min_highlights: int


@dataclass(frozen=True, slots=True)
class LedgerRow:
    media_id: str
    chapter: str
    placement: str
    type: str
    title: str
    creator_or_channel: str
    source_url: str
    embed_url_or_local_path: str
    license_or_terms: str
    verification_method: str
    verified_at: str
    caption_or_transcript_status: str
    alt_text_or_summary: str
    fallback: str
    public_use_ok: str
    status: str


def usage() -> str:
    return (
        "Usage: validate_multimedia.py --evidence-root PATH "
        "(--all | --chapter PATH --ledger FILE) "
        "[--min-media N] [--min-highlights N]"
    )


def parse_args(argv: list[str]) -> Args:
    if "--help" in argv or "-h" in argv:
        print(usage())
        raise SystemExit(0)

    values: dict[str, str] = {}
    flags: set[str] = set()
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--all":
            flags.add(token)
            index += 1
            continue
        if token in {"--evidence-root", "--chapter", "--ledger", "--min-media", "--min-highlights"}:
            if index + 1 >= len(argv):
                print(f"missing value for {token}", file=sys.stderr)
                raise SystemExit(2)
            values[token] = argv[index + 1]
            index += 2
            continue
        print(f"unknown argument: {token}", file=sys.stderr)
        raise SystemExit(2)

    evidence_root = values.get("--evidence-root")
    if evidence_root is None:
        print("missing --evidence-root", file=sys.stderr)
        raise SystemExit(2)

    chapter = values.get("--chapter")
    ledger = values.get("--ledger")
    all_chapters = "--all" in flags
    if all_chapters == (chapter is not None or ledger is not None):
        print("choose either --all or --chapter PATH --ledger FILE", file=sys.stderr)
        raise SystemExit(2)
    if (chapter is None) != (ledger is None):
        print("--chapter and --ledger must be used together", file=sys.stderr)
        raise SystemExit(2)

    return {
        "evidence_root": Path(evidence_root),
        "all_chapters": all_chapters,
        "chapter": Path(chapter) if chapter is not None else None,
        "ledger": ledger,
        "min_media": int(values.get("--min-media", "2")),
        "min_highlights": int(values.get("--min-highlights", "3")),
    }


def split_table_line(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    return [cell.strip().replace("\\|", "|") for cell in stripped.strip("|").split("|")]


def read_ledger(path: Path) -> tuple[list[LedgerRow], list[str]]:
    errors: list[str] = []
    if not path.exists():
        return [], [f"{path}: missing ledger"]

    lines = path.read_text(encoding="utf-8").splitlines()
    header_index = -1
    header: list[str] = []
    for line_index, line in enumerate(lines):
        cells = split_table_line(line)
        if "media_id" in cells:
            header_index = line_index
            header = cells
            break
    if header_index < 0:
        return [], [f"{path}: missing media ledger table header"]

    missing = [field for field in REQUIRED_FIELDS if field not in header]
    if missing:
        errors.append(f"{path}: missing fields {', '.join(missing)}")

    rows: list[LedgerRow] = []
    for line in lines[header_index + 2 :]:
        cells = split_table_line(line)
        if not cells or len(cells) != len(header):
            continue
        data = dict(zip(header, cells, strict=True))
        row = LedgerRow(**{field: data.get(field, "") for field in REQUIRED_FIELDS})
        rows.append(row)
    return rows, errors


def validate_chapter(chapter_path: Path, ledger_path: Path, min_media: int, min_highlights: int) -> list[str]:
    errors: list[str] = []
    if not chapter_path.exists():
        return [f"{chapter_path}: missing chapter"]

    text = chapter_path.read_text(encoding="utf-8")
    media_blocks = len(re.findall(r'class="[^"]*\bmedia-block\b', text))
    highlights = text.count("교재-highlight")
    if media_blocks < min_media:
        errors.append(f"{chapter_path}: expected at least {min_media} media-block entries, found {media_blocks}")
    if highlights < min_highlights:
        errors.append(f"{chapter_path}: expected at least {min_highlights} 교재-highlight entries, found {highlights}")

    if "youtube.com/embed" in text:
        errors.append(f"{chapter_path}: use youtube-nocookie.com for direct embeds")
    if "autoplay=1" in text:
        errors.append(f"{chapter_path}: autoplay=1 is forbidden")
    if re.search(r"!\[\s*\]", text):
        errors.append(f"{chapter_path}: image markdown with empty alt text")

    rows, ledger_errors = read_ledger(ledger_path)
    errors.extend(ledger_errors)
    public_rows = [row for row in rows if row.status != "omitted-unverified"]
    if len(public_rows) < min_media:
        errors.append(f"{ledger_path}: expected at least {min_media} public media rows, found {len(public_rows)}")

    for row in rows:
        if row.status not in ALLOWED_STATUSES:
            errors.append(f"{ledger_path}: {row.media_id} has invalid status {row.status}")
            continue
        if row.status == "omitted-unverified":
            continue
        if row.public_use_ok.lower() != "yes":
            errors.append(f"{ledger_path}: {row.media_id} public_use_ok must be yes")
        for field_name in REQUIRED_FIELDS:
            if not getattr(row, field_name):
                errors.append(f"{ledger_path}: {row.media_id} missing {field_name}")
        if row.status == "verified-embed":
            if "youtube-nocookie.com/embed/" not in row.embed_url_or_local_path:
                errors.append(f"{ledger_path}: {row.media_id} embed must use youtube-nocookie.com")
            if "autoplay=1" in row.embed_url_or_local_path:
                errors.append(f"{ledger_path}: {row.media_id} autoplay=1 is forbidden")
    return errors


def main() -> int:
    args = parse_args(sys.argv[1:])
    checks = CHAPTERS if args["all_chapters"] else ((str(args["chapter"]), str(args["ledger"])),)
    errors: list[str] = []
    for chapter, ledger in checks:
        chapter_path = Path(chapter)
        ledger_path = args["evidence_root"] / ledger
        errors.extend(validate_chapter(chapter_path, ledger_path, args["min_media"], args["min_highlights"]))
    if errors:
        print("FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
