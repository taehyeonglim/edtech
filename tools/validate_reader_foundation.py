#!/usr/bin/env python3
from __future__ import annotations

import json
import importlib.util
import sys
import re
from pathlib import Path
from typing import Any, Final

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PyYAML is required; install the MkDocs project dependencies first") from exc

ROOT: Final = Path(__file__).resolve().parents[1]
MKDOCS_CONFIG: Final = ROOT / "mkdocs.yml"
DOCS_DIR: Final = ROOT / "docs"
READER_DIR: Final = ROOT / "book-reader"

REQUIRED_PRESERVED_FILES: Final[tuple[Path, ...]] = (
    Path("index.html"),
    Path("chapters/index.html"),
    Path("book/index.html"),
    Path("book/text/index.html"),
    Path("assets/vendor/page-flip/page-flip.browser.js"),
    Path("assets/vendor/page-flip/LICENSE"),
    Path("assets/vendor/page-flip/METADATA.json"),
)

PRIVATE_MARKERS: Final[tuple[str, ...]] = (
    "/" + "Users/",
    "lecture-content" + "-maker-agent-team",
    "Previous_lecture" + "_content",
    "STATE" + ".json",
    "content" + "/chapters",
    "file:" + "//",
)
CDN_MARKERS: Final[tuple[str, ...]] = ("cdn" + ".jsdelivr", "unpkg" + ".com", "cd" + "njs")
STORAGE_API_MARKERS: Final[tuple[str, ...]] = (
    "local" + "Storage",
    "session" + "Storage",
    "document" + ".cookie",
    "indexed" + "DB",
    "navigator" + ".sendBeacon",
    "gtag" + "(",
    "Google" + "AnalyticsObject",
)
NETWORK_API_MARKERS: Final[tuple[str, ...]] = (
    "fetch" + "(",
    "XML" + "HttpRequest",
    "Web" + "Socket",
    "Event" + "Source",
)

READER_UX_HOOKS: Final[tuple[str, ...]] = (
    "data-reader-data",
    "data-reader-root",
    "data-reader-chapter",
    "data-reader-enhancement",
    "data-flip-book",
    "data-reader-page",
    "data-reader-controls",
    "data-page-prev",
    "data-page-next",
    "ArrowLeft",
    "ArrowRight",
    "prefers-reduced-motion: reduce",
    "URLSearchParams",
    "window.location.hash",
    "?chapter=ch03",
    "#ch03",
    "isRootReader",
    "flipIndex",
    "pageFlip.flip(flipIndex)",
    "usePortrait",
    "showCover: !isRootReader",
    "data-reader-cover",
    "reader-stage",
    "책장 넘김 뷰어",
    "static-content",
)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def read_json(path: Path) -> Any:
    return json.loads(read_text(path))


def existing_files_under(path: Path) -> list[Path]:
    if not path.exists():
        return []
    if path.is_file():
        return [path]
    return sorted(child for child in path.rglob("*") if child.is_file())


def load_mkdocs_config() -> tuple[dict[str, Any] | None, list[str]]:
    try:
        data = yaml.safe_load(read_text(MKDOCS_CONFIG))
    except Exception as exc:
        return None, [f"mkdocs.yml is unreadable or invalid: {exc}"]
    if not isinstance(data, dict):
        return None, ["mkdocs.yml did not parse to a mapping"]
    return data, []


def iter_nav_items(items: Any) -> list[tuple[str, str]]:
    discovered: list[tuple[str, str]] = []
    if not isinstance(items, list):
        return discovered
    for item in items:
        if isinstance(item, str) or not isinstance(item, dict):
            continue
        for title, value in item.items():
            if isinstance(value, str):
                discovered.append((str(title), value))
            elif isinstance(value, list):
                discovered.extend(iter_nav_items(value))
    return discovered


def nav_chapters(config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    chapters: list[dict[str, Any]] = []
    seen: set[str] = set()
    for title, target in iter_nav_items(config.get("nav")):
        parts = target.split("/")
        if len(parts) != 2 or not parts[0].startswith("part") or not parts[1].startswith("ch") or not parts[1].endswith(".md"):
            continue
        try:
            part = int(parts[0].removeprefix("part"))
            index = int(parts[1].removeprefix("ch").removesuffix(".md"))
        except ValueError:
            continue
        if target in seen:
            errors.append(f"duplicate chapter nav target: {target}")
            continue
        seen.add(target)
        source = Path(target)
        chapters.append(
            {
                "index": index,
                "part": part,
                "slug": f"ch{index:02d}",
                "title": title,
                "source": source,
                "sourceText": f"docs/{source.as_posix()}",
                "readerRoute": f"book-reader/ch{index:02d}/",
                "textRoute": f"book/{source.with_suffix('').as_posix()}/",
                "textHrefFromReader": f"../../book/{source.with_suffix('').as_posix()}/",
            }
        )
    chapters.sort(key=lambda row: row["index"])
    if [row["index"] for row in chapters] != list(range(1, 12)):
        errors.append(f"mkdocs.yml nav must define exactly chapter routes ch01-ch11; found {[row['slug'] for row in chapters]}")
    for row in chapters:
        if not (DOCS_DIR / row["source"]).is_file():
            errors.append(f"chapter source missing: {row['sourceText']}")
    return chapters, errors


def check_required_files(chapters: list[dict[str, Any]]) -> list[str]:
    errors = [f"missing required file: {path}" for path in REQUIRED_PRESERVED_FILES if not (ROOT / path).is_file()]
    errors.append("missing required file: tools/generate_book_reader.py") if not (ROOT / "tools/generate_book_reader.py").is_file() else None
    errors.append("missing required file: book-reader/reader-data.json") if not (READER_DIR / "reader-data.json").is_file() else None
    errors.append("missing required file: book-reader/index.html") if not (READER_DIR / "index.html").is_file() else None
    errors.extend(
        f"missing required reader chapter route: book-reader/{row['slug']}/index.html"
        for row in chapters
        if not (READER_DIR / row["slug"] / "index.html").is_file()
    )
    return errors


def check_manifest(chapters: list[dict[str, Any]]) -> list[str]:
    path = READER_DIR / "reader-data.json"
    if not path.is_file():
        return []
    errors: list[str] = []
    try:
        manifest = read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"book-reader/reader-data.json is unreadable or invalid: {exc}"]
    if not isinstance(manifest, dict):
        return ["book-reader/reader-data.json must be a JSON object"]
    if "_generated" in manifest:
        errors.append("book-reader/reader-data.json must not expose generated-file provenance")
    if "sourceConfig" in manifest or "sourceDocsDir" in manifest:
        errors.append("book-reader/reader-data.json must not expose source config paths")
    manifest_chapters = manifest.get("chapters")
    if not isinstance(manifest_chapters, list) or len(manifest_chapters) != 11:
        errors.append("book-reader/reader-data.json must contain exactly 11 chapters")
        manifest_chapters = []
    expected = [
        {
            "index": row["index"],
            "slug": row["slug"],
            "title": row["title"],
            "textHref": row["textHrefFromReader"],
            "readerRoute": row["readerRoute"],
            "textRoute": row["textRoute"],
        }
        for row in chapters
    ]
    comparable = [
        {key: chapter.get(key) for key in ("index", "slug", "title", "textHref", "readerRoute", "textRoute")}
        for chapter in manifest_chapters
        if isinstance(chapter, dict)
    ]
    if comparable != expected:
        errors.append("book-reader/reader-data.json chapters do not exactly match mkdocs.yml nav-derived chapter routes")
    routes = manifest.get("routes")
    if not isinstance(routes, dict):
        errors.append("book-reader/reader-data.json missing routes object")
    else:
        if routes.get("index") != "book-reader/index.html":
            errors.append("book-reader/reader-data.json routes.index must be book-reader/index.html")
        expected_chapter_files = [f"book-reader/{row['slug']}/index.html" for row in chapters]
        if routes.get("chapters") != expected_chapter_files:
            errors.append("book-reader/reader-data.json routes.chapters do not match ch01-ch11 generated files")
    vendor = manifest.get("vendor")
    if not isinstance(vendor, dict) or vendor.get("runtime") != "assets/vendor/page-flip/page-flip.browser.js":
        errors.append("book-reader/reader-data.json must identify the vendored page-flip runtime")
    return errors


def check_text_chapter_links(chapters: list[dict[str, Any]]) -> list[str]:
    path = ROOT / "book/text/index.html"
    if not path.is_file():
        return []
    text = read_text(path)
    errors: list[str] = []
    for row in chapters:
        legacy_href = f"../{row['source'].with_suffix('').as_posix()}/"
        if legacy_href not in text:
            errors.append(f"book/text/index.html missing chapter link: {legacy_href}")
        reader_href = f"../../book-reader/{row['slug']}/"
        if reader_href not in text:
            errors.append(f"book/text/index.html missing reader chapter link: {reader_href}")
    return errors


def check_vendor_identity() -> list[str]:
    metadata_path = ROOT / "assets/vendor/page-flip/METADATA.json"
    license_path = ROOT / "assets/vendor/page-flip/LICENSE"
    runtime_path = ROOT / "assets/vendor/page-flip/page-flip.browser.js"
    errors: list[str] = []
    try:
        metadata = read_json(metadata_path)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"assets/vendor/page-flip/METADATA.json is unreadable or invalid: {exc}"]
    expected = {
        "packageName": "page-flip",
        "version": "2.0.7",
        "license": "MIT",
        "runtimeFile": "page-flip.browser.js",
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            errors.append(f"assets/vendor/page-flip/METADATA.json expected {key}={value!r}, found {metadata.get(key)!r}")
    if metadata.get("name") not in {None, "page-flip"}:
        errors.append(f"assets/vendor/page-flip/METADATA.json expected name='page-flip', found {metadata.get('name')!r}")
    if license_path.is_file() and "MIT License" not in read_text(license_path):
        errors.append("assets/vendor/page-flip/LICENSE missing MIT License marker")
    if runtime_path.is_file() and runtime_path.stat().st_size < 40000:
        errors.append("assets/vendor/page-flip/page-flip.browser.js is unexpectedly small for page-flip 2.0.7 runtime")
    return errors


def check_route_chooser_links() -> list[str]:
    path = ROOT / "book/index.html"
    if not path.is_file():
        return []
    text = read_text(path)
    errors: list[str] = []
    for link in ("text/", "../book-reader/"):
        if link not in text:
            errors.append(f"book/index.html missing route chooser link: {link}")
    return errors


def check_reader_routes(chapters: list[dict[str, Any]]) -> list[str]:
    root_path = READER_DIR / "index.html"
    if not root_path.is_file():
        return []
    root_text = read_text(root_path)
    errors: list[str] = []
    for marker in ("data-reader-root", "data-reader-data", "data-reader-enhancement", "data-flip-book", "assets/vendor/page-flip/page-flip.browser.js"):
        if marker not in root_text:
            errors.append(f"book-reader/index.html missing G003 root reader hook: {marker}")
    if re.search(r"<script\b(?![^>]*\btype=[\"']application/json[\"'])(?![^>]*\bsrc=[\"']../assets/vendor/page-flip/page-flip\.browser\.js[\"'])[^>]*\bsrc=", root_text):
        errors.append("book-reader/index.html must load only the local vendored page-flip script")
    for row in chapters:
        slug = row["slug"]
        if f'{slug}/' not in root_text:
            errors.append(f"book-reader/index.html missing reader chapter link: {slug}/")
        chapter_path = READER_DIR / slug / "index.html"
        if not chapter_path.is_file():
            continue
        chapter_text = read_text(chapter_path)
        if "Generated reader output; do not edit generated output." in chapter_text:
            errors.append(f"book-reader/{slug}/index.html must not expose generated-file provenance")
        for marker in ("data-reader-chapter", "data-reader-data", "data-reader-enhancement", "data-flip-book", "data-reader-page", "data-reader-cover", "reader-stage", "data-reader-controls"):
            if marker not in chapter_text:
                errors.append(f"book-reader/{slug}/index.html missing G003 chapter reader hook: {marker}")
        if "책장 넘김 뷰어" not in chapter_text:
            errors.append(f"book-reader/{slug}/index.html missing full book-flip viewer label")
        if "책 넘김 미리보기" in chapter_text:
            errors.append(f"book-reader/{slug}/index.html still exposes preview-only copy")
        if chapter_text.count("data-reader-page") < 6:
            errors.append(f"book-reader/{slug}/index.html must generate multiple body reader pages, not a two-card preview")
        if "static-content" not in chapter_text or "전체 텍스트 본문" not in chapter_text:
            errors.append(f"book-reader/{slug}/index.html missing preserved full static text body below viewer")
        if row["textHrefFromReader"] not in chapter_text:
            errors.append(f"book-reader/{slug}/index.html missing exact text-mode link: {row['textHrefFromReader']}")
        if not re.search(r"<article\b[^>]*class=\"reader-content\"[^>]*>", chapter_text):
            errors.append(f"book-reader/{slug}/index.html missing static rendered article content wrapper")
        if re.search(r"<script\b(?![^>]*\btype=[\"']application/json[\"'])(?![^>]*\bsrc=[\"']../../assets/vendor/page-flip/page-flip\.browser\.js[\"'])[^>]*\bsrc=", chapter_text):
            errors.append(f"book-reader/{slug}/index.html must load only the local vendored page-flip script")
    unexpected = sorted(
        path.parent.name
        for path in READER_DIR.glob("ch*/index.html")
        if path.parent.name not in {row["slug"] for row in chapters}
    )
    errors.extend(f"unexpected reader chapter route: book-reader/{slug}/index.html" for slug in unexpected)
    return errors


def check_reader_ux_hooks() -> list[str]:
    generator_path = ROOT / "tools/generate_book_reader.py"
    if not generator_path.is_file():
        return []
    generator_text = read_text(generator_path)
    errors = [f"tools/generate_book_reader.py missing G003 UX hook string: {marker}" for marker in READER_UX_HOOKS if marker not in generator_text]
    script_region = generator_text.split("def script() -> str:", 1)[-1].split("def reader_data_script", 1)[0]
    if any(marker in script_region for marker in STORAGE_API_MARKERS):
        errors.append("tools/generate_book_reader.py must not use browser storage")
    if any(marker in script_region for marker in NETWORK_API_MARKERS):
        errors.append("tools/generate_book_reader.py must not use backend/network APIs for reader data")
    return errors


def check_no_md_href_leaks(paths: tuple[Path, ...]) -> list[str]:
    errors: list[str] = []
    md_href = re.compile(r"\b(?:href|src)=[\"'][^\"']+\.md(?:[?#/\"'])", re.IGNORECASE)
    for relative in paths:
        for path in existing_files_under(ROOT / relative):
            try:
                text = read_text(path)
            except OSError as exc:
                errors.append(f"{path.relative_to(ROOT)}: could not read for .md href scan: {exc}")
                continue
            if md_href.search(text):
                errors.append(f"{path.relative_to(ROOT)} contains .md href/src leak")
    return errors
def check_generated_outputs_synced() -> list[str]:
    generator_path = ROOT / "tools/generate_book_reader.py"
    if not generator_path.is_file():
        return ["missing generator: tools/generate_book_reader.py"]
    spec = importlib.util.spec_from_file_location("_edtech_book_reader_generator", generator_path)
    if spec is None or spec.loader is None:
        return ["could not load tools/generate_book_reader.py for sync validation"]
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        generator_errors: list[str] = []
        generator_warnings: list[str] = []
        config = module.load_mkdocs_config()
        module.validate_static_prereqs(generator_errors)
        chapters = module.discover_chapters(config, generator_errors)
        extensions = module.markdown_extensions(config, generator_errors, generator_warnings)
        rendered = {chapter.slug: module.render_markdown(chapter, extensions, generator_errors) for chapter in chapters}
        outputs = module.output_map(chapters, rendered) if chapters else {}
        if outputs:
            module.validate_outputs(outputs, chapters, generator_errors)
    except Exception as exc:
        return [f"generator dry-run sync validation failed: {exc}"]
    errors = [f"generator dry-run error: {error}" for error in generator_errors]
    errors.extend(f"generator dry-run warning: {warning}" for warning in generator_warnings)
    for path, expected_text in outputs.items():
        if not path.is_file():
            errors.append(f"generated output missing; run generator --write: {path.relative_to(ROOT)}")
            continue
        actual_text = read_text(path)
        if actual_text != expected_text:
            errors.append(f"generated output is not synchronized with docs/mkdocs; run generator --write: {path.relative_to(ROOT)}")
    return errors



def check_workflow_reader_foundation() -> list[str]:
    path = ROOT / ".github/workflows/deploy.yml"
    if not path.is_file():
        return ["missing workflow: .github/workflows/deploy.yml"]
    text = read_text(path)
    try:
        workflow = yaml.safe_load(text)
    except Exception as exc:
        return [f".github/workflows/deploy.yml is invalid YAML: {exc}"]
    try:
        steps = workflow["jobs"]["build"]["steps"]
    except (KeyError, TypeError):
        return [".github/workflows/deploy.yml missing jobs.build.steps"]
    if not isinstance(steps, list):
        return [".github/workflows/deploy.yml jobs.build.steps must be a list"]

    run_steps: list[tuple[int, list[str]]] = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or "run" not in step:
            continue
        run_value = step["run"]
        if not isinstance(run_value, str):
            continue
        lines = [line.strip() for line in run_value.splitlines() if line.strip() and not line.strip().startswith("#")]
        run_steps.append((index, lines))

    def first_step_with_exact(command: str) -> int | None:
        for index, lines in run_steps:
            if command in lines:
                return index
        return None

    errors: list[str] = []
    generator_step = first_step_with_exact("python3 tools/generate_book_reader.py --mode release --write")
    validator_step = first_step_with_exact("python3 tools/validate_reader_foundation.py")
    mkdocs_step = first_step_with_exact("mkdocs build --strict")
    for label, step_index in (("generator", generator_step), ("validator", validator_step), ("mkdocs strict build", mkdocs_step)):
        if step_index is None:
            errors.append(f".github/workflows/deploy.yml missing active {label} run step")
    if None not in (generator_step, validator_step, mkdocs_step) and not (generator_step < validator_step < mkdocs_step):
        errors.append(".github/workflows/deploy.yml must run generator before validator before mkdocs build --strict")

    flattened_lines = [line for _, lines in run_steps for line in lines]
    required_assembly_lines = (
        "cp index.html _site/index.html",
        "cp -r chapters _site/chapters",
        "cp -r site _site/book",
        "cp book/index.html _site/book/index.html",
        "mkdir -p _site/book/text",
        "cp -r book/text/. _site/book/text/",
        "cp -r book-reader _site/book-reader",
        "cp -r assets _site/assets",
    )
    errors.extend(
        f".github/workflows/deploy.yml missing active assemble command: {command}"
        for command in required_assembly_lines
        if command not in flattened_lines
    )
    return errors


def check_markers(paths: tuple[Path, ...], markers: tuple[str, ...], label: str) -> list[str]:
    errors: list[str] = []
    for relative in paths:
        for path in existing_files_under(ROOT / relative):
            try:
                text = read_text(path)
            except OSError as exc:
                errors.append(f"{path.relative_to(ROOT)}: could not read for {label} scan: {exc}")
                continue
            for marker in markers:
                if marker in text:
                    errors.append(f"{path.relative_to(ROOT)}: forbidden {label} marker found: {marker}")
    return errors


def validate() -> list[str]:
    errors: list[str] = []
    config, config_errors = load_mkdocs_config()
    errors.extend(config_errors)
    chapters: list[dict[str, Any]] = []
    if config is not None:
        chapters, chapter_errors = nav_chapters(config)
        errors.extend(chapter_errors)
    errors.extend(check_required_files(chapters))
    errors.extend(check_manifest(chapters))
    errors.extend(check_text_chapter_links(chapters))
    errors.extend(check_vendor_identity())
    errors.extend(check_route_chooser_links())
    errors.extend(check_reader_routes(chapters))
    errors.extend(check_reader_ux_hooks())
    errors.extend(check_generated_outputs_synced())
    errors.extend(check_workflow_reader_foundation())
    errors.extend(check_markers((Path("book"), Path("book-reader"), Path("assets/vendor/page-flip/METADATA.json")), PRIVATE_MARKERS, "local/private"))
    errors.extend(check_markers((Path("book"), Path("book-reader"), Path("assets/vendor/page-flip/METADATA.json")), CDN_MARKERS, "CDN"))
    errors.extend(check_markers((Path("book"), Path("book-reader")), STORAGE_API_MARKERS, "storage/API"))
    errors.extend(check_markers((Path("book"), Path("book-reader"), Path("assets/vendor/page-flip/page-flip.browser.js")), NETWORK_API_MARKERS, "network/backend API"))
    errors.extend(check_no_md_href_leaks((Path("book"), Path("book-reader"))))
    return errors


def main() -> int:
    errors = validate()
    if errors:
        print(f"reader foundation validation failed: {len(errors)} issue(s)")
        for error in errors:
            print(f"- {error}")
        return 1
    print("reader foundation validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
