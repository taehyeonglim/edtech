#!/usr/bin/env python3
"""Validate visual provenance, accessibility, sizing, and target density."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "assets" / "visual-sources.json"
VISUAL_REF = re.compile(r"(?:\.\./){1,4}(assets/visuals/[A-Za-z0-9_./-]+\.(?:jpg|jpeg|png|webp))")
DECK_REF = re.compile(
    r'src:\s*"(?P<src>(?:\.\./){1,4}assets/visuals/[^"\s]+)"(?P<body>.{0,700}?)alt:\s*"(?P<alt>[^"]*)"',
    re.DOTALL,
)
DOC_REF = re.compile(
    r'<img\s+src="(?P<src>(?:\.\./){1,4}assets/visuals/[^"\s]+)"\s+alt="(?P<alt>[^"]*)"',
    re.DOTALL,
)
LAYOUT = re.compile(r'layout:\s*"([a-z]+)"')
FOCUS_ID = re.compile(r'id:\s*"[^"]+-focus"')
CHAPTER_VISUAL = re.compile(r'<figure class="chapter-visual">')
VISUAL_LAYOUTS = {"figure", "split"}
MAX_BYTES = 300 * 1024
TARGET_WIDTH = 1600
TARGET_HEIGHT = 900


def jpeg_size(path: Path) -> tuple[int, int] | None:
    data = path.read_bytes()
    if not data.startswith(b"\xff\xd8"):
        return None
    offset = 2
    while offset + 9 < len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        offset += 2
        if marker in {0xD8, 0xD9}:
            continue
        if offset + 2 > len(data):
            break
        length = int.from_bytes(data[offset:offset + 2], "big")
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            height = int.from_bytes(data[offset + 3:offset + 5], "big")
            width = int.from_bytes(data[offset + 5:offset + 7], "big")
            return width, height
        if length < 2:
            break
        offset += length
    return None


def normalize_ref(value: str) -> str:
    match = re.search(r"assets/visuals/.+", value)
    return match.group(0) if match else value


def main() -> int:
    errors: list[str] = []
    if not MANIFEST.exists():
        print("Visual asset validation failed:\n- assets/visual-sources.json is missing", file=sys.stderr)
        return 1

    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"Visual asset validation failed:\n- manifest is invalid: {exc}", file=sys.stderr)
        return 1

    allowed = set(data.get("policy", {}).get("allowed_external_licenses", []))
    entries = data.get("assets", [])
    registered: dict[str, dict[str, object]] = {}
    for index, entry in enumerate(entries):
        path_value = entry.get("path")
        if not isinstance(path_value, str) or not path_value:
            errors.append(f"manifest asset #{index + 1}: missing path")
            continue
        if path_value in registered:
            errors.append(f"manifest: duplicate path: {path_value}")
            continue
        registered[path_value] = entry
        asset = ROOT / path_value
        if not asset.is_file():
            errors.append(f"manifest: file does not exist: {path_value}")
            continue
        if asset.stat().st_size > MAX_BYTES:
            errors.append(f"{path_value}: {asset.stat().st_size} bytes exceeds {MAX_BYTES}")
        size = jpeg_size(asset)
        if size != (TARGET_WIDTH, TARGET_HEIGHT):
            errors.append(f"{path_value}: expected {TARGET_WIDTH}x{TARGET_HEIGHT}, found {size}")
        kind = entry.get("type")
        if kind == "external":
            if entry.get("license") not in allowed:
                errors.append(f"{path_value}: disallowed or missing external license: {entry.get('license')}")
            for field in ("title", "author", "original_page"):
                if not entry.get(field):
                    errors.append(f"{path_value}: external asset missing {field}")
        elif kind == "generated":
            if entry.get("generator") != "OpenAI GPT Image":
                errors.append(f"{path_value}: generated asset must identify OpenAI GPT Image")
            if not isinstance(entry.get("prompt"), str) or len(entry["prompt"].strip()) < 40:
                errors.append(f"{path_value}: generated asset prompt is missing or too short")
        else:
            errors.append(f"{path_value}: unknown asset type: {kind}")

    on_disk = {
        path.relative_to(ROOT).as_posix()
        for folder in (ROOT / "assets" / "visuals" / "generated", ROOT / "assets" / "visuals" / "wiki")
        for path in folder.glob("*")
        if path.is_file()
    }
    for path in sorted(on_disk - set(registered)):
        errors.append(f"unregistered visual asset: {path}")
    for path in sorted(set(registered) - on_disk):
        errors.append(f"registered visual is outside the managed asset folders or missing: {path}")

    referenced: set[str] = set()
    deck_layouts: list[str] = []
    focus_count = 0
    for deck_path in sorted((ROOT / "chapters").glob("chapter-*/slides/deck.html")):
        text = deck_path.read_text(encoding="utf-8")
        deck_layouts.extend(LAYOUT.findall(text))
        focus_count += len(FOCUS_ID.findall(text))
        raw_refs = {normalize_ref(match.group(1)) for match in VISUAL_REF.finditer(text)}
        described = set()
        for match in DECK_REF.finditer(text):
            source = normalize_ref(match.group("src"))
            described.add(source)
            if not match.group("alt").strip():
                errors.append(f"{deck_path.relative_to(ROOT)}: empty alt for {source}")
            after = text[match.end():match.end() + 800]
            if registered.get(source, {}).get("type") == "external" and "source:" not in after:
                errors.append(f"{deck_path.relative_to(ROOT)}: external asset lacks visible source: {source}")
        for source in sorted(raw_refs - described):
            errors.append(f"{deck_path.relative_to(ROOT)}: visual reference lacks nearby alt: {source}")
        referenced.update(raw_refs)

    chapter_visuals = 0
    for doc_path in sorted((ROOT / "docs").glob("part*/ch*.md")):
        text = doc_path.read_text(encoding="utf-8")
        chapter_visuals += len(CHAPTER_VISUAL.findall(text))
        raw_refs = {normalize_ref(match.group(1)) for match in VISUAL_REF.finditer(text)}
        described = set()
        for match in DOC_REF.finditer(text):
            source = normalize_ref(match.group("src"))
            described.add(source)
            if not match.group("alt").strip():
                errors.append(f"{doc_path.relative_to(ROOT)}: empty alt for {source}")
        for source in sorted(raw_refs - described):
            errors.append(f"{doc_path.relative_to(ROOT)}: visual reference lacks alt: {source}")
        referenced.update(raw_refs)

    for path in sorted(referenced - set(registered)):
        errors.append(f"referenced visual is not registered: {path}")
    for path in sorted(set(registered) - referenced):
        errors.append(f"registered visual is unused: {path}")

    total_slides = len(deck_layouts)
    visual_slides = sum(layout in VISUAL_LAYOUTS for layout in deck_layouts)
    density = visual_slides / total_slides if total_slides else 0
    if total_slides != 281:
        errors.append(f"slide count regression: expected 281, found {total_slides}")
    if focus_count != 23:
        errors.append(f"visual-focus slide count regression: expected 23, found {focus_count}")
    if visual_slides != 113 or density < 0.40:
        errors.append(f"visual density regression: expected 113/281 (>=40%), found {visual_slides}/{total_slides} ({density:.1%})")
    if chapter_visuals != 15:
        errors.append(f"textbook visual placement regression: expected 15, found {chapter_visuals}")

    if errors:
        print("Visual asset validation failed:", file=sys.stderr)
        print("\n".join(f"- {error}" for error in errors), file=sys.stderr)
        return 1
    print(
        "Visual asset validation passed: "
        f"{len(registered)} registered assets, {focus_count} focus slides, "
        f"{visual_slides}/{total_slides} visual slides ({density:.1%}), "
        f"{chapter_visuals} textbook placements"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
