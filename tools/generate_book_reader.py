#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any, Final

try:
    import markdown
except ImportError as exc:  # pragma: no cover - exercised in release CI when deps are absent
    raise SystemExit("Python-Markdown is required; install the MkDocs project dependencies first") from exc

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PyYAML is required; install the MkDocs project dependencies first") from exc

ROOT: Final = Path(__file__).resolve().parents[1]
DOCS_DIR: Final = ROOT / "docs"
MKDOCS_CONFIG: Final = ROOT / "mkdocs.yml"
READER_DIR: Final = ROOT / "book-reader"
VENDOR_RUNTIME: Final = ROOT / "assets/vendor/page-flip/page-flip.browser.js"
VENDOR_LICENSE: Final = ROOT / "assets/vendor/page-flip/LICENSE"
VENDOR_METADATA: Final = ROOT / "assets/vendor/page-flip/METADATA.json"
GENERATOR_NAME: Final = "tools/generate_book_reader.py"
CHAPTER_RE: Final = re.compile(r"^part(?P<part>\d+)/ch(?P<chapter>\d{2})\.md$")
LOCAL_LINK_RE: Final = re.compile(r"(?P<attr>\b(?:href|src)=)(?P<quote>[\"'])(?P<target>[^\"']+)(?P=quote)")

def marker_text(*parts: str) -> str:
    return "".join(parts)

FORBIDDEN_OUTPUT_MARKERS: Final[tuple[str, ...]] = (
    marker_text("/", "Users", "/"),
    marker_text("lecture-content-maker-agent", "-team"),
    marker_text("Previous", "_lecture_content"),
    marker_text("STATE", ".json"),
    marker_text("content", "/", "chapters"),
    marker_text("file", "://"),
    marker_text("cdn", ".", "jsdelivr"),
    marker_text("unpkg", ".", "com"),
    marker_text("cd", "njs"),
    marker_text("local", "Storage"),
    marker_text("session", "Storage"),
    marker_text("document", ".", "cookie"),
    marker_text("indexed", "DB"),
    marker_text("navigator", ".", "sendBeacon"),
    marker_text("gtag", "("),
    marker_text("Google", "AnalyticsObject"),
    marker_text("fetch", "("),
    marker_text("XML", "HttpRequest"),
    marker_text("Web", "Socket"),
    marker_text("Event", "Source"),
)

ALLOWED_HTML_TAGS: Final[set[str]] = {
    "a",
    "abbr",
    "audio",
    "b",
    "blockquote",
    "br",
    "cite",
    "code",
    "dd",
    "del",
    "details",
    "div",
    "dl",
    "dt",
    "em",
    "figcaption",
    "figure",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "iframe",
    "img",
    "ins",
    "kbd",
    "li",
    "mark",
    "ol",
    "p",
    "picture",
    "pre",
    "small",
    "source",
    "span",
    "strong",
    "sub",
    "summary",
    "sup",
    "svg",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "ul",
    "video",
}
ALLOWED_HTML_ATTR_PREFIXES: Final[tuple[str, ...]] = ("aria-", "data-")
ALLOWED_HTML_ATTRS: Final[set[str]] = {
    "allow",
    "allowfullscreen",
    "alt",
    "class",
    "colspan",
    "controls",
    "height",
    "href",
    "id",
    "loading",
    "poster",
    "rel",
    "rowspan",
    "src",
    "style",
    "target",
    "title",
    "type",
    "width",
}


@dataclass(frozen=True)
class Chapter:
    index: int
    title: str
    source: Path
    part: int
    slug: str

    @property
    def source_posix(self) -> str:
        return self.source.as_posix()

    @property
    def text_href_from_reader_chapter(self) -> str:
        return f"../../book/{self.source.with_suffix('').as_posix()}/"

    @property
    def reader_href_from_index(self) -> str:
        return f"{self.slug}/"


class RawHtmlValidator(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._check(tag, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._check(tag, attrs)

    def _check(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() not in ALLOWED_HTML_TAGS:
            self.errors.append(f"unsupported raw HTML tag <{tag}>")
        for name, value in attrs:
            lowered = name.lower()
            if lowered.startswith("on"):
                self.errors.append(f"unsupported event handler attribute {name!r} on <{tag}>")
            elif lowered not in ALLOWED_HTML_ATTRS and not lowered.startswith(ALLOWED_HTML_ATTR_PREFIXES):
                self.errors.append(f"unsupported raw HTML attribute {name!r} on <{tag}>")
            if value and re.search(r"^\s*javascript:", value, re.IGNORECASE):
                self.errors.append(f"unsupported javascript URL on <{tag} {name}>")


def load_mkdocs_config() -> dict[str, Any]:
    with MKDOCS_CONFIG.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError("mkdocs.yml did not parse to a mapping")
    return data


def iter_nav_items(items: Any) -> list[tuple[str, str]]:
    discovered: list[tuple[str, str]] = []
    if not isinstance(items, list):
        return discovered
    for item in items:
        if isinstance(item, str):
            continue
        if not isinstance(item, dict):
            continue
        for title, value in item.items():
            if isinstance(value, str):
                discovered.append((str(title), value))
            elif isinstance(value, list):
                discovered.extend(iter_nav_items(value))
    return discovered


def discover_chapters(config: dict[str, Any], errors: list[str]) -> list[Chapter]:
    chapters: list[Chapter] = []
    seen_sources: set[str] = set()
    for title, target in iter_nav_items(config.get("nav")):
        match = CHAPTER_RE.match(target)
        if not match:
            continue
        if target in seen_sources:
            errors.append(f"duplicate chapter nav target: {target}")
            continue
        seen_sources.add(target)
        source = Path(target)
        chapter_num = int(match.group("chapter"))
        chapters.append(
            Chapter(
                index=chapter_num,
                title=title,
                source=source,
                part=int(match.group("part")),
                slug=f"ch{chapter_num:02d}",
            )
        )
    chapters.sort(key=lambda chapter: chapter.index)
    expected = list(range(1, 12))
    actual = [chapter.index for chapter in chapters]
    if actual != expected:
        errors.append(f"mkdocs nav must expose exactly chapters 01-11 in order; found {actual}")
    for chapter in chapters:
        if not (DOCS_DIR / chapter.source).is_file():
            errors.append(f"chapter source missing: docs/{chapter.source_posix}")
    return chapters


def markdown_extensions(config: dict[str, Any], errors: list[str], warnings: list[str]) -> list[Any]:
    configured = config.get("markdown_extensions") or []
    extensions: list[Any] = []
    for entry in configured:
        if isinstance(entry, str):
            extensions.append(entry)
        elif isinstance(entry, dict):
            for name, options in entry.items():
                extensions.append({name: options or {}})
        else:
            warnings.append(f"ignored unsupported markdown extension config entry: {entry!r}")
    required = {"admonition", "footnotes", "attr_list", "md_in_html", "tables"}
    names = {entry if isinstance(entry, str) else next(iter(entry)) for entry in extensions}
    missing = sorted(required - names)
    if missing:
        errors.append(f"mkdocs.yml missing required Markdown extensions for reader rendering: {', '.join(missing)}")
    return extensions


def extension_configs(extensions: list[Any]) -> tuple[list[str], dict[str, dict[str, Any]]]:
    names: list[str] = []
    configs: dict[str, dict[str, Any]] = {}
    for entry in extensions:
        if isinstance(entry, str):
            names.append(entry)
        else:
            name, options = next(iter(entry.items()))
            names.append(name)
            configs[name] = options if isinstance(options, dict) else {}
    return names, configs


def validate_source_markdown(chapter: Chapter, text: str) -> list[str]:
    errors: list[str] = []
    if "!!!" in text and not re.search(r"^!!!\s+\w+", text, re.MULTILINE):
        errors.append(f"docs/{chapter.source_posix}: possible malformed admonition marker")
    if re.search(r"^\s*\|", text, re.MULTILINE) and "---" not in text:
        errors.append(f"docs/{chapter.source_posix}: possible table without separator row")
    raw_validator = RawHtmlValidator()
    try:
        raw_validator.feed(text)
    except Exception as exc:  # HTMLParser is lenient; this is defensive.
        errors.append(f"docs/{chapter.source_posix}: raw HTML parse failed: {exc}")
    errors.extend(f"docs/{chapter.source_posix}: {error}" for error in sorted(set(raw_validator.errors)))
    return errors


def rewrite_local_links(rendered: str, chapter: Chapter, errors: list[str]) -> str:
    source_parent = chapter.source.parent

    def replace(match: re.Match[str]) -> str:
        attr = match.group("attr")
        quote = match.group("quote")
        target = match.group("target")
        split_target = urlsplit(target)
        if split_target.scheme or split_target.netloc or target.startswith(("mailto:", "tel:", "#")):
            return match.group(0)
        path_target = split_target.path
        suffix = ("?" + split_target.query if split_target.query else "") + ("#" + split_target.fragment if split_target.fragment else "")
        if path_target.startswith("/"):
            errors.append(f"docs/{chapter.source_posix}: root-absolute link is not portable in reader output: {target}")
            return match.group(0)
        if path_target.startswith("../") or path_target.startswith("./"):
            resolved = (source_parent / path_target).as_posix()
        else:
            resolved = (source_parent / path_target).as_posix()
        resolved = re.sub(r"/\.(/|$)", "/", resolved)
        while "../" in resolved:
            parts: list[str] = []
            for part in resolved.split("/"):
                if part == "..":
                    if parts:
                        parts.pop()
                    else:
                        errors.append(f"docs/{chapter.source_posix}: link escapes docs directory: {target}")
                        return match.group(0)
                elif part != ".":
                    parts.append(part)
            resolved = "/".join(parts)
        if resolved.endswith(".md"):
            href = "../../book/" + resolved[:-3] + "/" + suffix
        elif re.search(r"\.(png|jpe?g|gif|svg|webp|avif|mp4|webm|mp3|wav|pdf)$", resolved, re.IGNORECASE):
            asset = DOCS_DIR / resolved
            if not asset.exists():
                errors.append(f"docs/{chapter.source_posix}: linked asset missing: docs/{resolved}")
            href = "../../book/" + resolved + suffix
        else:
            href = target
        return f"{attr}{quote}{html.escape(href, quote=True)}{quote}"

    return LOCAL_LINK_RE.sub(replace, rendered)


def render_markdown(chapter: Chapter, extensions: list[Any], errors: list[str]) -> str:
    source_path = DOCS_DIR / chapter.source
    text = source_path.read_text(encoding="utf-8")
    errors.extend(validate_source_markdown(chapter, text))
    names, configs = extension_configs(extensions)
    try:
        md = markdown.Markdown(extensions=names, extension_configs=configs, output_format="html5")
        rendered = md.convert(text)
    except Exception as exc:
        errors.append(f"docs/{chapter.source_posix}: Markdown render failed: {exc}")
        return ""
    rendered = rewrite_local_links(rendered, chapter, errors)
    if re.search(r"^!!!\s+", rendered, re.MULTILINE):
        errors.append(f"docs/{chapter.source_posix}: admonition marker survived rendering")
    if re.search(r"^\[\^[^\]]+\]:", rendered, re.MULTILINE):
        errors.append(f"docs/{chapter.source_posix}: footnote definition survived rendering")
    return rendered


def css() -> str:
    return """
:root { --navy:#0b2c5c; --blue:#1b66c9; --ink:#1a1a1a; --muted:#5c6470; --line:#c5d2e3; --paper:#fffdf8; --ivory:#fff8e8; --soft:#eef4fb; --gold:#b8892f; --shadow:rgba(11,44,92,.14); }
* { box-sizing:border-box; }
html { scroll-behavior:smooth; }
body { margin:0; overflow-x:hidden; background:linear-gradient(180deg,var(--navy) 0 240px,var(--ivory) 240px,#fff 68%); color:var(--ink); font-family:"Pretendard","Noto Sans KR","Malgun Gothic",system-ui,sans-serif; line-height:1.72; }
body::before { content:""; position:fixed; inset:0; pointer-events:none; background:radial-gradient(circle at 12% 0,rgba(255,248,232,.22),transparent 32rem),linear-gradient(90deg,rgba(11,44,92,.08),transparent 18%,transparent 82%,rgba(11,44,92,.08)); }
a { color:var(--blue); text-underline-offset:.18em; }
a:focus-visible, button:focus-visible, [tabindex]:focus-visible { outline:3px solid var(--gold); outline-offset:3px; }
.wrap { width:min(1120px,calc(100% - 40px)); margin:0 auto; position:relative; }
.topnav { display:flex; gap:12px; flex-wrap:wrap; padding:20px 0 0; font-weight:900; font-size:.95rem; }
.topnav a { color:#fff8e8; text-decoration:none; }
.topnav span { color:rgba(255,248,232,.55); }
.hero { padding:44px 0 28px; color:#fff8e8; }
.eyebrow { margin:0 0 10px; color:#d8c89d; font-size:.92rem; font-weight:900; letter-spacing:.14em; text-transform:uppercase; }
h1 { margin:0; color:inherit; font-size:clamp(2rem,4.8vw,3.65rem); line-height:1.08; font-weight:900; letter-spacing:-.03em; }
.lead { max-width:850px; margin:16px 0 0; color:#f4eddc; font-weight:700; font-size:1.05rem; }
.reader-panel { margin:0 auto 64px; padding:28px; border:1px solid var(--line); border-radius:20px; background:rgba(255,253,248,.96); box-shadow:0 22px 54px var(--shadow); }
.reader-panel h2, .reader-panel h3 { color:var(--navy); }
.reader-panel > h2:first-child { margin-top:0; }
.gateway { display:grid; grid-template-columns:minmax(0,.92fr) minmax(300px,1.08fr); gap:24px; align-items:start; }
.reader-enhancement { display:none; }
.reader-enhancement[data-enhanced="true"] { display:block; }
.preview-card { padding:22px; border:1px solid var(--line); border-radius:16px; background:linear-gradient(145deg,#fff,var(--ivory)); box-shadow:inset 6px 0 0 rgba(184,137,47,.35); }
.preview-kicker { margin:0 0 8px; color:var(--muted); font-weight:900; letter-spacing:.09em; text-transform:uppercase; }
.preview-title { margin:0 0 8px; color:var(--navy); font-size:clamp(1.45rem,3vw,2rem); line-height:1.18; }
.preview-links { display:flex; flex-wrap:wrap; gap:10px; margin-top:16px; }
.chapter-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; margin:22px 0 0; padding:0; list-style:none; }
.chapter-card { display:block; min-height:104px; padding:18px; border:1px solid var(--line); border-radius:12px; background:var(--paper); color:inherit; text-decoration:none; transition:border-color .18s ease, transform .18s ease, box-shadow .18s ease; }
.chapter-card:hover, .chapter-card[aria-current="page"] { border-color:var(--gold); transform:translateY(-2px); box-shadow:0 12px 28px rgba(11,44,92,.13); }
.num { display:inline-flex; margin-bottom:8px; padding:4px 9px; background:var(--navy); color:white; border-radius:2px; font-weight:900; letter-spacing:.08em; }
.title { display:block; color:var(--navy); font-size:1.05rem; font-weight:900; }
.source-note { display:block; color:var(--muted); font-size:.9rem; overflow-wrap:anywhere; }
.notice, .admonition { margin:20px 0; padding:16px 18px; border-left:6px solid var(--blue); background:var(--soft); color:var(--muted); font-weight:700; }
.button-row { display:flex; flex-wrap:wrap; gap:10px; margin:22px 0; }
.button { display:inline-flex; align-items:center; justify-content:center; min-height:44px; padding:0 16px; border:1px solid var(--navy); border-radius:5px; background:#fff; color:var(--navy); font:inherit; font-weight:900; text-decoration:none; cursor:pointer; }
.button.primary { background:var(--navy); color:white; }
.reader-layout { display:grid; grid-template-columns:minmax(0,1fr) 270px; gap:24px; align-items:start; }
.reader-content { min-width:0; user-select:text; }
.reader-content, .reader-content * { overflow-wrap:anywhere; }
.reader-content pre { overflow-x:auto; white-space:pre-wrap; }
.reader-content code { white-space:pre-wrap; word-break:break-word; }
.reader-content h1, .reader-content h2, .reader-content h3 { color:var(--navy); line-height:1.25; }
.reader-content img, .reader-content video, .reader-content iframe { max-width:100%; border:0; }
.reader-content iframe { width:100%; aspect-ratio:16/9; }
.reader-content table { display:block; width:100%; max-width:100%; overflow-x:auto; border-collapse:collapse; margin:18px 0; }
.reader-content th, .reader-content td { border:1px solid var(--line); padding:10px 12px; vertical-align:top; }
.reader-content th { background:var(--soft); color:var(--navy); }
.media-block { margin:24px 0; padding:18px; border:1px solid var(--line); border-radius:14px; background:var(--paper); }
.media-kicker { margin:0 0 4px; color:var(--blue); font-weight:900; }
.media-title { margin:0 0 14px; color:var(--navy); font-size:1.16rem; font-weight:900; }
.media-grid, .media-flow, .media-axis { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:10px; }
.media-panel, .flow-node, .axis-cell { padding:12px; border:1px solid var(--line); border-radius:10px; background:white; }
.media-source { color:var(--muted); font-size:.92rem; }
.reader-sidebar { position:sticky; top:14px; padding:16px; border:1px solid var(--line); border-radius:14px; background:var(--soft); }
.reader-sidebar ol { margin:10px 0 0; padding-left:22px; }
.reader-sidebar a { text-decoration:none; font-weight:800; }
.flip-area { margin:24px 0 0; padding:18px; border:1px dashed var(--line); border-radius:16px; background:white; }
.flip-area[hidden], .reader-controls[hidden] { display:none !important; }
.flip-book { width:100%; max-width:100%; min-height:220px; margin:0 auto; }
.reader-page { width:360px; min-height:480px; padding:24px; border:1px solid var(--line); background:linear-gradient(90deg,rgba(11,44,92,.05),transparent 18px),var(--paper); color:var(--ink); overflow:hidden; }
.reader-page h3 { margin-top:0; }
.reader-controls { display:flex; flex-wrap:wrap; gap:10px; margin-top:14px; align-items:center; }
.reader-status { color:var(--muted); font-weight:800; }
footer { border-top:1px solid var(--line); background:var(--soft); color:var(--muted); }
footer .wrap { padding:24px 0; font-size:.95rem; font-weight:700; }
@media (prefers-reduced-motion: reduce) { html { scroll-behavior:auto; } *, *::before, *::after { animation-duration:.001ms !important; animation-iteration-count:1 !important; transition-duration:.001ms !important; } }
@media (max-width:900px) { .gateway, .reader-layout { grid-template-columns:1fr; } .reader-sidebar { position:static; } .reader-panel { padding:22px; } }
@media (max-width:640px) { .wrap { width:min(100% - 24px,1120px); } .chapter-grid { grid-template-columns:1fr; } .reader-page { width:280px; min-height:400px; padding:18px; } .button { flex:1 1 160px; } }
""".strip()


def script() -> str:
    return """
(function () {
  var DATA_SELECTOR = "[data-reader-data]";
  function ready(fn) {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", fn, { once: true });
    else fn();
  }
  function readData() {
    var node = document.querySelector(DATA_SELECTOR);
    if (!node) return null;
    try { return JSON.parse(node.textContent || "{}"); }
    catch (error) { return null; }
  }
  function chapterFromUrl(data) {
    if (!data || !data.chapters) return null;
    var params = new URLSearchParams(window.location.search);
    var requested = (params.get("chapter") || window.location.hash.replace(/^#/, "") || "").toLowerCase();
    if (!requested) return null;
    return data.chapters.find(function (chapter) {
      return chapter.slug === requested || String(chapter.index).padStart(2, "0") === requested.replace(/^ch/, "");
    }) || null;
  }
  function shouldIgnoreKeyboard(event) {
    var target = event.target;
    var tag = target && target.tagName ? target.tagName.toLowerCase() : "";
    return event.altKey || event.ctrlKey || event.metaKey || event.defaultPrevented || tag === "input" || tag === "textarea" || tag === "select" || (target && target.isContentEditable);
  }
  ready(function () {
    var data = readData();
    var reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var holder = document.querySelector("[data-flip-book]");
    var controls = document.querySelector("[data-reader-controls]");
    var status = document.querySelector("[data-reader-status]");
    var chapters = data && data.chapters ? data.chapters : [];
    var selected = chapterFromUrl(data);
    var currentSlug = data && data.current ? String(data.current).toLowerCase() : "";
    var current = currentSlug ? chapters.find(function (chapter) { return chapter.slug === currentSlug; }) : null;
    var activeIndex = selected ? chapters.findIndex(function (chapter) { return chapter.slug === selected.slug; }) : (current ? chapters.findIndex(function (chapter) { return chapter.slug === current.slug; }) : 0);
    if (activeIndex < 0) activeIndex = 0;

    function setSelected(chapter, pushHash) {
      if (!chapter) return;
      document.querySelectorAll("[data-chapter-link]").forEach(function (link) {
        if (link.getAttribute("data-chapter-link") === chapter.slug) link.setAttribute("aria-current", "page");
        else link.removeAttribute("aria-current");
      });
      var title = document.querySelector("[data-preview-title]");
      var source = document.querySelector("[data-preview-source]");
      var reader = document.querySelector("[data-preview-reader]");
      var text = document.querySelector("[data-preview-text]");
      if (title) title.textContent = chapter.index.toString().padStart(2, "0") + ". " + chapter.title;
      if (source) source.textContent = "선택한 장의 텍스트 장을 함께 제공합니다.";
      if (reader) reader.setAttribute("href", chapter.readerHref || chapter.readerRoute || chapter.slug + "/");
      if (text) text.setAttribute("href", chapter.textHref || "../book/" + chapter.textRoute.replace(/^book\\//, ""));
      if (status) status.textContent = "현재 페이지 " + chapter.index.toString().padStart(2, "0");
      if (pushHash && window.history && window.location.hash !== "#" + chapter.slug) {
        window.history.replaceState(null, "", "#" + chapter.slug);
      }
    }

    setSelected(chapters[activeIndex], false);

    if (!holder || reducedMotion || !window.St || !window.St.PageFlip) {
      if (controls) controls.hidden = true;
      return;
    }

    document.querySelectorAll("[data-reader-enhancement]").forEach(function (node) {
      node.setAttribute("data-enhanced", "true");
    });

    var pageFlip = new window.St.PageFlip(holder, {
      width: 360,
      height: 480,
      size: "stretch",
      minWidth: 280,
      maxWidth: 720,
      minHeight: 360,
      maxHeight: 860,
      maxShadowOpacity: 0.16,
      showCover: false,
      mobileScrollSupport: true
    });
    pageFlip.loadFromHTML(document.querySelectorAll("[data-reader-page]"));
    if (typeof pageFlip.flip === "function" && activeIndex > 0) pageFlip.flip(activeIndex);
    if (controls) controls.hidden = false;

    var prev = document.querySelector("[data-page-prev]");
    var next = document.querySelector("[data-page-next]");
    function move(delta) {
      activeIndex = Math.max(0, Math.min(chapters.length - 1, activeIndex + delta));
      setSelected(chapters[activeIndex], true);
      if (delta < 0 && pageFlip.flipPrev) pageFlip.flipPrev();
      if (delta > 0 && pageFlip.flipNext) pageFlip.flipNext();
    }
    if (prev) prev.addEventListener("click", function () { move(-1); });
    if (next) next.addEventListener("click", function () { move(1); });
    document.addEventListener("keydown", function (event) {
      if (shouldIgnoreKeyboard(event)) return;
      if (event.key === "ArrowLeft") { move(-1); }
      if (event.key === "ArrowRight") { move(1); }
    });
  });
}());
""".strip()


def reader_data_script(payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f'  <script type="application/json" data-reader-data>{data}</script>'


def chapter_payloads(chapters: list[Chapter], from_index: bool) -> list[dict[str, Any]]:
    return [
        {
            "index": chapter.index,
            "slug": chapter.slug,
            "title": chapter.title,
            "readerRoute": f"book-reader/{chapter.slug}/",
            "readerHref": chapter.reader_href_from_index if from_index else f"../{chapter.slug}/",
            "textRoute": f"book/{chapter.source.with_suffix('').as_posix()}/",
            "textHref": f"../book/{chapter.source.with_suffix('').as_posix()}/" if from_index else chapter.text_href_from_reader_chapter,
        }
        for chapter in chapters
    ]


def page_shell(title: str, description: str, body: str, asset_prefix: str, payload: dict[str, Any]) -> str:
    data_block = reader_data_script(payload)
    return f"""<!doctype html>
<html lang=\"ko\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <meta name=\"author\" content=\"임태형\">
  <meta name=\"description\" content=\"{html.escape(description, quote=True)}\">
  <title>{html.escape(title)} · 책 넘김 모드</title>
  <style>{css()}</style>
  <script src=\"{asset_prefix}assets/vendor/page-flip/page-flip.browser.js\" defer></script>
</head>
<body>
{body}
  <footer><div class=\"wrap\">교육방법 및 교육공학 · 책 넘김 모드</div></footer>
{data_block}
  <script>{script()}</script>
</body>
</html>
"""


def build_index(chapters: list[Chapter]) -> str:
    payload = {"schemaVersion": 1, "page": "reader-root", "chapters": chapter_payloads(chapters, True)}
    cards = "\n".join(
        f"      <li><a class=\"chapter-card\" data-chapter-link=\"{chapter.slug}\" href=\"{chapter.reader_href_from_index}#content\"><span class=\"num\">{chapter.index:02d}</span><span class=\"title\">{html.escape(chapter.title)}</span><span class=\"source-note\">텍스트 모드와 책 넘김 모드 제공</span></a></li>"
        for chapter in chapters
    )
    preview_pages = "\n".join(
        f"          <section class=\"reader-page\" data-reader-page id=\"{chapter.slug}\"><h3>{chapter.index:02d}. {html.escape(chapter.title)}</h3><p>{html.escape(chapter.title)} 장으로 이동할 수 있습니다.</p><p><a href=\"{chapter.reader_href_from_index}\">리더 장 열기</a></p><p><a href=\"../book/{chapter.source.with_suffix('').as_posix()}/\">텍스트 장 열기</a></p></section>"
        for chapter in chapters
    )
    body = f"""  <nav class=\"topnav wrap\" aria-label=\"상위 경로\"><a href=\"../\">홈</a><span aria-hidden=\"true\">|</span><a href=\"../book/\">교재 선택</a><span aria-hidden=\"true\">|</span><a href=\"../book/text/\">텍스트 모드</a></nav>
  <header class=\"hero wrap\"><p class=\"eyebrow\">교육방법 및 교육공학</p><h1>책 넘김 모드</h1><p class=\"lead\">정적 HTML 목차가 먼저 제공되고, 브라우저가 허용할 때만 책장 넘김 미리보기가 더해집니다.</p></header>
  <main class=\"reader-panel wrap gateway\" aria-label=\"책 넘김 목차\" data-reader-root>
    <section aria-labelledby=\"toc-title\">
      <h2 id=\"toc-title\">장 선택</h2>
      <p class="notice">텍스트 교재와 책 넘김 모드를 함께 탐색할 수 있습니다. URL은 <code>#ch03</code> 또는 <code>?chapter=ch03</code> 형식을 지원합니다.</p>
      <ol class=\"chapter-grid\">
{cards}
      </ol>
    </section>
    <section class=\"reader-enhancement\" data-reader-enhancement aria-labelledby=\"preview-title\">
      <div class=\"preview-card\">
        <p class=\"preview-kicker\">선택한 장</p>
        <h2 class=\"preview-title\" id=\"preview-title\" data-preview-title>{chapters[0].index:02d}. {html.escape(chapters[0].title)}</h2>
        <p class="source-note" data-preview-source>선택한 장의 텍스트 장을 함께 제공합니다.</p>
        <div class=\"preview-links\"><a class=\"button primary\" data-preview-reader href=\"{chapters[0].reader_href_from_index}\">리더 장 열기</a><a class=\"button\" data-preview-text href=\"../book/{chapters[0].source.with_suffix('').as_posix()}/\">텍스트 장 열기</a></div>
      </div>
      <div class=\"flip-area\" aria-label=\"책 넘김 미리보기\">
        <div class=\"flip-book\" data-flip-book>
{preview_pages}
        </div>
        <div class=\"reader-controls\" data-reader-controls hidden><button class=\"button\" type=\"button\" data-page-prev>이전 페이지</button><button class=\"button\" type=\"button\" data-page-next>다음 페이지</button><span class=\"reader-status\" data-reader-status aria-live=\"polite\"></span></div>
      </div>
    </section>
  </main>"""
    return page_shell("책 넘김 목차", "교육방법 및 교육공학 책 넘김 모드 목차", body, "../", payload)


def build_chapter(chapter: Chapter, chapters: list[Chapter], rendered: str) -> str:
    payload = {"schemaVersion": 1, "page": "reader-chapter", "current": chapter.slug, "chapters": chapter_payloads(chapters, False)}
    nav_items = "\n".join(
        f"        <li><a href=\"../{item.slug}/\" data-chapter-link=\"{item.slug}\"{' aria-current=\"page\"' if item.slug == chapter.slug else ''}>{item.index:02d}. {html.escape(item.title)}</a></li>" for item in chapters
    )
    prev_chapter = next((item for item in chapters if item.index == chapter.index - 1), None)
    next_chapter = next((item for item in chapters if item.index == chapter.index + 1), None)
    prev_link = f"<a class=\"button\" href=\"../{prev_chapter.slug}/\">이전 장</a>" if prev_chapter else ""
    next_link = f"<a class=\"button\" href=\"../{next_chapter.slug}/\">다음 장</a>" if next_chapter else ""
    body = f"""  <nav class=\"topnav wrap\" aria-label=\"상위 경로\"><a href=\"../\">책 넘김 목차</a><span aria-hidden=\"true\">|</span><a href=\"../../book/\">교재 선택</a><span aria-hidden=\"true\">|</span><a href=\"{chapter.text_href_from_reader_chapter}\">텍스트 장</a></nav>
  <header class=\"hero wrap\"><p class=\"eyebrow\">교육방법 및 교육공학 · Chapter {chapter.index:02d}</p><h1>{html.escape(chapter.title)}</h1><p class=\"lead\">전체 본문은 정적 HTML로 먼저 렌더링되어 텍스트 선택·복사와 링크 이동이 JavaScript 없이도 작동합니다.</p></header>
  <main class=\"reader-panel wrap reader-layout\" aria-label=\"{chapter.index:02d}장 리더\" data-reader-chapter=\"{chapter.slug}\">
    <article class=\"reader-content\" id=\"content\">
      <div class=\"button-row\"><a class=\"button primary\" href=\"{chapter.text_href_from_reader_chapter}\">텍스트 장 읽기</a><a class=\"button\" href=\"../\">책 넘김 목차</a>{prev_link}{next_link}</div>
{rendered}
      <section class=\"flip-area reader-enhancement\" data-reader-enhancement aria-label=\"책 넘김 미리보기\">
        <h2>책 넘김 미리보기</h2>
        <p class=\"notice\">본문 일부를 카드처럼 넘기며 장의 흐름을 확인할 수 있습니다. 전체 본문은 위 장 콘텐츠에서 선택하거나 복사해서 이용할 수 있습니다.</p>
        <div class=\"flip-book\" data-flip-book>
          <section class="reader-page" data-reader-page><h3>{html.escape(chapter.title)}</h3><p>본문을 카드처럼 넘기며 읽기 흐름을 확인합니다.</p><p><a href="{chapter.text_href_from_reader_chapter}">텍스트 장으로 이동</a></p></section>
          <section class=\"reader-page\" data-reader-page><h3>읽기 경로</h3><p><a href=\"{chapter.text_href_from_reader_chapter}\">텍스트 장으로 이동</a></p><p><a href=\"../\">책 넘김 목차로 이동</a></p></section>
        </div>
        <div class=\"reader-controls\" data-reader-controls hidden><button class=\"button\" type=\"button\" data-page-prev>이전 페이지</button><button class=\"button\" type=\"button\" data-page-next>다음 페이지</button><span class=\"reader-status\" data-reader-status aria-live=\"polite\"></span></div>
      </section>
    </article>
    <aside class=\"reader-sidebar\" aria-label=\"책 넘김 장 목록\">
      <strong>장 목록</strong>
      <ol>
{nav_items}
      </ol>
    </aside>
  </main>"""
    return page_shell(chapter.title, f"교육방법 및 교육공학 책 넘김 모드 {chapter.index:02d}장", body, "../../", payload)


def manifest(chapters: list[Chapter]) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "vendor": {
            "runtime": "assets/vendor/page-flip/page-flip.browser.js",
            "metadata": "assets/vendor/page-flip/METADATA.json",
            "license": "assets/vendor/page-flip/LICENSE",
        },
        "routes": {
            "index": "book-reader/index.html",
            "chapters": [f"book-reader/{chapter.slug}/index.html" for chapter in chapters],
        },
        "chapters": [
            {
                "index": chapter.index,
                "slug": chapter.slug,
                "title": chapter.title,
                "textHref": chapter.text_href_from_reader_chapter,
                "readerRoute": f"book-reader/{chapter.slug}/",
                "textRoute": f"book/{chapter.source.with_suffix('').as_posix()}/",
            }
            for chapter in chapters
        ],
    }


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def output_map(chapters: list[Chapter], rendered: dict[str, str]) -> dict[Path, str]:
    outputs = {READER_DIR / "index.html": build_index(chapters)}
    for chapter in chapters:
        outputs[READER_DIR / chapter.slug / "index.html"] = build_chapter(chapter, chapters, rendered[chapter.slug])
    outputs[READER_DIR / "reader-data.json"] = json.dumps(manifest(chapters), ensure_ascii=False, indent=2) + "\n"
    return outputs


def validate_outputs(outputs: dict[Path, str], chapters: list[Chapter], errors: list[str]) -> None:
    expected_paths = {READER_DIR / "index.html", READER_DIR / "reader-data.json"}
    expected_paths.update(READER_DIR / chapter.slug / "index.html" for chapter in chapters)
    if set(outputs) != expected_paths:
        errors.append("internal output set did not match expected reader routes")
    for chapter in chapters:
        chapter_text = outputs[READER_DIR / chapter.slug / "index.html"]
        if chapter.text_href_from_reader_chapter not in chapter_text:
            errors.append(f"book-reader/{chapter.slug}/index.html missing text route {chapter.text_href_from_reader_chapter}")
        for marker in ("data-reader-chapter", "data-reader-data", "data-reader-enhancement", "data-flip-book", "data-reader-page", "data-reader-controls", "ArrowLeft", "ArrowRight", "prefers-reduced-motion: reduce", "URLSearchParams", "window.location.hash"):
            if marker not in chapter_text:
                errors.append(f"book-reader/{chapter.slug}/index.html missing reader UX hook {marker}")
    index_text = outputs[READER_DIR / "index.html"]
    for marker in ("data-reader-root", "data-reader-data", "data-reader-enhancement", "data-flip-book", "data-reader-controls", "assets/vendor/page-flip/page-flip.browser.js", "#ch03", "?chapter=ch03"):
        if marker not in index_text:
            errors.append(f"book-reader/index.html missing reader UX hook {marker}")
    for chapter in chapters:
        if chapter.reader_href_from_index not in index_text:
            errors.append(f"book-reader/index.html missing chapter route {chapter.reader_href_from_index}")
    for output_path, text in outputs.items():
        for marker in FORBIDDEN_OUTPUT_MARKERS:
            if marker in text:
                errors.append(f"{output_path.relative_to(ROOT)} contains forbidden marker: {marker}")
        if re.search(r"\b(?:href|src)=[\"'][^\"']+\.md(?:[?#/\"'])", text, re.IGNORECASE):
            errors.append(f"{output_path.relative_to(ROOT)} contains .md href/src leak")


def validate_static_prereqs(errors: list[str]) -> None:
    for path in (VENDOR_RUNTIME, VENDOR_LICENSE, VENDOR_METADATA):
        if not path.is_file():
            errors.append(f"missing vendored page-flip file: {path.relative_to(ROOT)}")
    if VENDOR_METADATA.is_file():
        try:
            metadata = json.loads(VENDOR_METADATA.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"invalid page-flip metadata JSON: {exc}")
        else:
            expected = {"packageName": "page-flip", "version": "2.0.7", "license": "MIT", "runtimeFile": "page-flip.browser.js"}
            for key, value in expected.items():
                if metadata.get(key) != value:
                    errors.append(f"page-flip metadata expected {key}={value!r}, found {metadata.get(key)!r}")


def write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(mode: str, write: bool, report_path: Path | None) -> int:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        config = load_mkdocs_config()
    except Exception as exc:
        errors.append(f"failed to read mkdocs.yml: {exc}")
        config = {}
    validate_static_prereqs(errors)
    chapters = discover_chapters(config, errors) if config else []
    extensions = markdown_extensions(config, errors, warnings) if config else []
    rendered: dict[str, str] = {}
    for chapter in chapters:
        rendered[chapter.slug] = render_markdown(chapter, extensions, errors)
    outputs = output_map(chapters, rendered) if chapters and all(chapter.slug in rendered for chapter in chapters) else {}
    if outputs:
        validate_outputs(outputs, chapters, errors)
    if mode == "development" and errors:
        warnings.extend(errors)
        errors = []
    if write and not errors:
        for path, text in outputs.items():
            write_file(path, text)
    report = {
        "mode": mode,
        "write": write,
        "ok": not errors,
        "chapterCount": len(chapters),
        "chapters": [
            {"index": chapter.index, "slug": chapter.slug, "title": chapter.title, "textRoute": f"book/{chapter.source.with_suffix('').as_posix()}/"}
            for chapter in chapters
        ],
        "outputs": [str(path.relative_to(ROOT)) for path in sorted(outputs)] if outputs else [],
        "warnings": warnings,
        "errors": errors,
    }
    if report_path:
        write_report(report_path, report)
    if errors:
        print(f"reader generation failed: {len(errors)} issue(s)", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    if warnings:
        print(f"reader generation completed with {len(warnings)} warning(s)")
        for warning in warnings:
            print(f"- {warning}")
    else:
        print("reader generation passed")
    if write:
        print(f"wrote {len(outputs)} generated reader file(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the static book-reader route from MkDocs chapter Markdown.")
    parser.add_argument("--mode", choices=("development", "release"), default="development")
    parser.add_argument("--write", action="store_true", help="write generated book-reader outputs")
    parser.add_argument("--report", type=Path, help="write a JSON generation report")
    args = parser.parse_args(argv)
    return run(args.mode, args.write, args.report)


if __name__ == "__main__":
    raise SystemExit(main())
