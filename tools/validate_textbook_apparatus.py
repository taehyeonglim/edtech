#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

try:
    import yaml
except ImportError as exc:  # pragma: no cover - supplied by the existing MkDocs dependency set
    raise SystemExit("PyYAML is required by this repository's validation tools") from exc

ROOT: Final = Path(__file__).resolve().parents[1]
DEFAULT_CHAPTERS: Final[tuple[Path, ...]] = (
    Path("docs/part1/ch01.md"),
    Path("docs/part1/ch02.md"),
    Path("docs/part2/ch03.md"),
    Path("docs/part2/ch04.md"),
    Path("docs/part2/ch05.md"),
    Path("docs/part3/ch06.md"),
    Path("docs/part3/ch07.md"),
    Path("docs/part3/ch08.md"),
    Path("docs/part4/ch09.md"),
    Path("docs/part4/ch10.md"),
    Path("docs/part4/ch11.md"),
)
CHAPTERS_BY_ID: Final[dict[str, Path]] = {path.stem: path for path in DEFAULT_CHAPTERS}
DEFAULT_MIGRATION_FILE: Final = Path("quality/apparatus-migration.yml")

REQUIRED_HEADINGS: Final[tuple[str, ...]] = (
    "## 도입 사례",
    "## 핵심 용어",
    "## 이론과 연구 확장",
    "## 토론 질문",
    "## 형성 평가",
    "## 참고문헌",
)

FOOTNOTE_REF_RE: Final = re.compile(r"(?<!\[)\[\^([A-Za-z0-9_.:-]+)\](?!:)")
FOOTNOTE_DEF_RE: Final = re.compile(r"^\[\^([^\]]+)\]:", re.MULTILINE)
HEADING_RE: Final = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
LIST_ITEM_RE: Final = re.compile(r"^(?:\d+\.|[-*])\s+", re.MULTILINE)
ASSESSMENT_ITEM_RE: Final = re.compile(r"^\d+\.\s+", re.MULTILINE)
CORE_REFERENCE_RE: Final = re.compile(r"\[\^[^\]]+\]")
NUMBERED_BODY_HEADING_RE: Final = re.compile(r"^\d+\.\s+\S+")
MARKDOWN_TABLE_ROW_RE: Final = re.compile(r"^\|.*\|\s*$", re.MULTILINE)
CHOICE_MARKER_RE: Final = re.compile(r"[①②③④⑤⑥⑦⑧⑨]|(?<!\w)[A-Da-d][.)]")
MEDIA_BLOCK_RE: Final = re.compile(r'class="[^\"]*\bmedia-block\b[^\"]*"')
MARKDOWN_IMAGE_RE: Final = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
HTML_IMAGE_RE: Final = re.compile(r"<img\b(?P<attributes>[^>]*)>", re.IGNORECASE)
INLINE_SVG_RE: Final = re.compile(r"<svg\b", re.IGNORECASE)
PRIVATE_MARKER_PARTS: Final[tuple[tuple[str, ...], ...]] = (
    ("/", "Users", "/"),
    ("lecture-content-maker-agent", "-team"),
    ("Previous", "_lecture_content"),
    ("STATE", ".json"),
    ("content", "/", "chapters"),
    ("file", "://"),
)


@dataclass(frozen=True)
class ChapterAudit:
    path: str
    status: str
    counts: dict[str, int]
    errors: list[str]


def marker_text(*parts: str) -> str:
    return "".join(parts)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate textbook chapter apparatus and citation structure.")
    parser.add_argument(
        "--chapters",
        nargs="+",
        metavar="CHAPTER[,CHAPTER...]",
        help="Chapter IDs (for example ch01,ch02) or markdown paths to audit. Defaults to all 11 chapters.",
    )
    parser.add_argument(
        "--migration",
        default=str(DEFAULT_MIGRATION_FILE),
        help="Migration YAML that selects chapters using the standard apparatus rules.",
    )
    parser.add_argument("--report", help="Optional JSON report path.")
    return parser.parse_args()


def rel(path: Path) -> Path:
    try:
        return path.relative_to(ROOT)
    except ValueError:
        return path


def section(text: str, heading: str) -> str:
    pattern = re.compile(rf"^{re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return ""
    next_heading = re.search(r"^##\s+", text[match.end() :], re.MULTILINE)
    end = match.end() + next_heading.start() if next_heading else len(text)
    return text[match.end() : end].strip()
def has_heading(text: str, heading: str) -> bool:
    return any(match.group(0).strip() == heading for match in HEADING_RE.finditer(text))


def top_level_headings(text: str) -> list[str]:
    return [match.group(1).strip() for match in HEADING_RE.finditer(text)]


def count_list_items(body: str) -> int:
    return len(LIST_ITEM_RE.findall(body))


def count_visual_aids(text: str) -> int:
    """Count reader-visible CSS/SVG/image learning aids without prescribing one markup form."""
    return (
        len(MEDIA_BLOCK_RE.findall(text))
        + len(MARKDOWN_IMAGE_RE.findall(text))
        + len(HTML_IMAGE_RE.findall(text))
        + len(INLINE_SVG_RE.findall(text))
    )


def standard_structure_errors(text: str) -> list[str]:
    """Check the standard's ##-level apparatus order, leaving body prose unconstrained."""
    errors: list[str] = []
    headings = top_level_headings(text)
    standard_headings = (
        "학습 목표",
        "사전 읽기와 학습목표 대응표",
        "도입 사례",
        "개념 오해와 적용 한계",
        "생각해 보기",
        "웹 학습 보조",
        "이론과 연구 확장",
        "토론 질문",
        "형성 평가",
        "요약",
        "핵심 용어",
        "참고문헌",
    )
    positions: dict[str, int] = {}
    for heading in standard_headings:
        matches = [index for index, title in enumerate(headings) if title == heading]
        if not matches:
            errors.append(f"missing standard heading: ## {heading}")
        elif len(matches) > 1:
            errors.append(f"standard heading must appear once: ## {heading}")
        else:
            positions[heading] = matches[0]

    ordered_headings = (
        "학습 목표",
        "사전 읽기와 학습목표 대응표",
        "도입 사례",
        "개념 오해와 적용 한계",
        "생각해 보기",
        "웹 학습 보조",
        "이론과 연구 확장",
        "토론 질문",
        "형성 평가",
        "요약",
        "핵심 용어",
        "참고문헌",
    )
    for earlier, later in zip(ordered_headings, ordered_headings[1:]):
        if earlier in positions and later in positions and positions[earlier] >= positions[later]:
            errors.append(f"standard section order: ## {earlier} must precede ## {later}")

    opening = positions.get("도입 사례")
    misconception = positions.get("개념 오해와 적용 한계")
    if opening is not None and misconception is not None:
        body_headings = headings[opening + 1 : misconception]
        if not body_headings:
            errors.append("missing numbered body sections between opening case and misconceptions")
        for heading in body_headings:
            if not NUMBERED_BODY_HEADING_RE.match(heading):
                errors.append(f"body section must use a numbered ## heading: ## {heading}")

    standard_set = set(standard_headings)
    for index, heading in enumerate(headings):
        if heading in standard_set:
            continue
        in_body_range = opening is not None and misconception is not None and opening < index < misconception
        if not in_body_range or not NUMBERED_BODY_HEADING_RE.match(heading):
            errors.append(f"unexpected ## heading outside the standard body sequence: ## {heading}")
    return errors


def standard_requirement_errors(text: str) -> list[str]:
    """Check observable minimums for a chapter that has opted into the standard."""
    errors: list[str] = []
    objectives = section(text, "## 학습 목표")
    correspondence = section(text, "## 사전 읽기와 학습목표 대응표")
    misconceptions = section(text, "## 개념 오해와 적용 한계")
    reflection = section(text, "## 생각해 보기")
    assessment = section(text, "## 형성 평가")

    objective_count = count_list_items(objectives)
    if not 3 <= objective_count <= 5:
        errors.append(f"learning objectives must number 3-5, found {objective_count}")
    if len(MARKDOWN_TABLE_ROW_RE.findall(correspondence)) < 2:
        errors.append("pre-reading/objective correspondence must include a Markdown table")
    if count_list_items(misconceptions) < 1:
        errors.append("misconceptions and application limits must include at least one item")

    reflection_count = count_list_items(reflection)
    if not 2 <= reflection_count <= 3:
        errors.append(f"reflection questions must number 2-3, found {reflection_count}")

    visual_aid_count = count_visual_aids(text)
    if not 2 <= visual_aid_count <= 4:
        errors.append(f"visual learning aids must number 2-4, found {visual_aid_count}")
    for image in MARKDOWN_IMAGE_RE.findall(text):
        if not image.strip():
            errors.append("Markdown image is missing alt text")
    for match in HTML_IMAGE_RE.finditer(text):
        alt_match = re.search(r"\balt\s*=\s*(['\"])(.*?)\1", match.group("attributes"), re.IGNORECASE)
        if alt_match is None or not alt_match.group(2).strip():
            errors.append("HTML image is missing non-empty alt text")

    items = assessment_items(text)
    choice_count = sum(1 for item in items if CHOICE_MARKER_RE.search(item))
    constructed_count = sum(
        1
        for item in items
        if re.search(r"\*\*(?:예시 답안|채점 기준|루브릭)\*\*", item) is not None
    )
    if choice_count < 3:
        errors.append(f"formative assessment must include at least 3 multiple-choice items, found {choice_count}")
    if constructed_count < 1:
        errors.append(f"formative assessment must include at least 1 constructed-response item, found {constructed_count}")
    return errors




def count_glossary_entries(text: str) -> int:
    terms = section(text, "## 핵심 용어")
    if not terms:
        return 0
    return len(LIST_ITEM_RE.findall(terms))


def expansion_blocks(text: str) -> list[str]:
    expanded = section(text, "## 이론과 연구 확장")
    if not expanded:
        return []
    matches = list(re.finditer(r"^###\s+.+?\s*$", expanded, re.MULTILINE))
    blocks: list[str] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(expanded)
        blocks.append(expanded[match.start() : end].strip())
    return blocks


def count_expansion_blocks(text: str) -> int:
    return len(expansion_blocks(text))
def count_discussion_questions(text: str) -> int:
    discussion = section(text, "## 토론 질문")
    if not discussion:
        return 0
    return len(LIST_ITEM_RE.findall(discussion))



def assessment_items(text: str) -> list[str]:
    assessment = section(text, "## 형성 평가")
    if not assessment:
        return []
    matches = list(re.finditer(r"^\d+\.\s+", assessment, re.MULTILINE))
    items: list[str] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(assessment)
        items.append(assessment[match.start() : end].strip())
    return items


def count_assessment_questions(text: str) -> int:
    return len(assessment_items(text))


def count_answered_assessment_items(text: str) -> int:
    answered = 0
    for item in assessment_items(text):
        has_answer = re.search(r"\*\*(?:정답|예시 답안)\*\*", item) is not None
        has_rationale = re.search(r"\*\*(?:채점 기준|루브릭|해설)\*\*", item) is not None
        if has_answer and has_rationale:
            answered += 1
    return answered


def count_cited_expansion_blocks(text: str) -> int:
    return sum(1 for block in expansion_blocks(text) if CORE_REFERENCE_RE.search(block))


INTERNAL_ID_RE: Final = re.compile(
    r"ch\d{2}-(?:obj|act|assess|src|o\d|fa|precheck|apply|prework|cumulative|check)[a-z0-9-]*"
)
EDITORIAL_RESIDUE: Final[tuple[str, ...]] = (
    "metadata verified",
    "verified at",
    "metadata inspected",
    "Crossref metadata",
    "oEmbed",
)
CAPTION_RE: Final = re.compile(r"^\*그림\s+([^.]*)\.", re.MULTILINE)


def reader_visible_text(text: str) -> str:
    """Body as students see it: front matter and HTML comments removed."""
    without_front_matter = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.DOTALL)
    return re.sub(r"<!--.*?-->", "", without_front_matter, flags=re.DOTALL)


def publishing_hygiene_errors(text: str, chapter_number: int) -> list[str]:
    """Catch editing infrastructure that leaked onto the student-facing page."""
    errors: list[str] = []
    visible = reader_visible_text(text)

    exposed = sorted(set(INTERNAL_ID_RE.findall(visible)))
    if exposed:
        errors.append(
            "internal tracking ids must stay in HTML comments, found on the page: "
            + ", ".join(exposed)
        )

    residue = sorted({phrase for phrase in EDITORIAL_RESIDUE if phrase in visible})
    if residue:
        errors.append("editorial verification notes must not ship: " + ", ".join(residue))

    for caption in CAPTION_RE.findall(visible):
        if not re.fullmatch(rf"{chapter_number}-\d+", caption.strip()):
            errors.append(f"figure captions must read '그림 {chapter_number}-N.', found '그림 {caption}.'")
    return errors


def audit_chapter(path: Path, use_standard: bool) -> ChapterAudit:
    errors: list[str] = []
    relative = rel(path)
    if not path.is_file():
        return ChapterAudit(str(relative), "failed", {}, ["chapter file is missing"])

    text = path.read_text(encoding="utf-8")
    errors.extend(publishing_hygiene_errors(text, int(path.stem.removeprefix("ch"))))
    if use_standard:
        errors.extend(standard_structure_errors(text))
        errors.extend(standard_requirement_errors(text))
    else:
        for heading in REQUIRED_HEADINGS:
            if not has_heading(text, heading):
                errors.append(f"missing required heading: {heading}")

    scenario = section(text, "## 도입 사례")
    if not scenario:
        errors.append("missing opening case/scenario body")
    elif "창작 시나리오" not in scenario and "가상 사례" not in scenario and "실제 사례" not in scenario:
        errors.append("opening case must label whether it is a created or real case")

    glossary_count = count_glossary_entries(text)
    expansion_count = count_expansion_blocks(text)
    discussion_count = count_discussion_questions(text)
    assessment_count = count_assessment_questions(text)
    answered_assessment_count = count_answered_assessment_items(text)
    expansion_citation_count = count_cited_expansion_blocks(text)
    refs = set(FOOTNOTE_REF_RE.findall(text))
    defs = set(FOOTNOTE_DEF_RE.findall(text))
    unresolved = sorted(refs - defs)
    unused = sorted(defs - refs)
    private_hits = [marker_text(*parts) for parts in PRIVATE_MARKER_PARTS if marker_text(*parts) in text]

    if not 3 <= glossary_count <= 5:
        errors.append(f"core glossary count must be 3-5, found {glossary_count}")
    if not 2 <= expansion_count <= 4:
        errors.append(f"theory/research expansion blocks must be 2-4, found {expansion_count}")
    if expansion_citation_count < expansion_count:
        errors.append("each theory/research expansion block should include at least one footnote citation")
    if discussion_count < 3:
        errors.append(f"discussion questions must be at least 3, found {discussion_count}")
    if use_standard:
        if answered_assessment_count < assessment_count:
            errors.append(f"assessment answers/rationales/rubrics must cover each item, found {answered_assessment_count}/{assessment_count}")
    else:
        if assessment_count < 5:
            errors.append(f"assessment questions must be at least 5, found {assessment_count}")
        if answered_assessment_count < assessment_count or answered_assessment_count < 5:
            errors.append(f"assessment answers/rationales/rubrics must cover each item, found {answered_assessment_count}/{assessment_count}")
    if not refs:
        errors.append("chapter has no footnote citations")
    if unresolved:
        errors.append(f"unresolved footnote references: {', '.join(unresolved)}")
    if unused:
        errors.append(f"unused footnote definitions: {', '.join(unused)}")
    if private_hits:
        errors.append(f"private/source marker leaked: {', '.join(private_hits)}")

    counts = {
        "glossaryEntries": glossary_count,
        "expansionBlocks": expansion_count,
        "expansionCitations": expansion_citation_count,
        "discussionQuestions": discussion_count,
        "assessmentQuestions": assessment_count,
        "assessmentAnswerMarkers": answered_assessment_count,
        "footnoteReferences": len(refs),
        "footnoteDefinitions": len(defs),
    }
    return ChapterAudit(str(relative), "passed" if not errors else "failed", counts, errors)


def load_migrated_chapters(path: Path) -> tuple[set[str], list[str]]:
    """Load the explicit, reviewed chapter-by-chapter standard migration gate."""
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return set(), [f"migration file is unreadable or invalid YAML: {rel(path)}: {exc}"]
    if not isinstance(value, dict):
        return set(), [f"migration file must be a YAML mapping: {rel(path)}"]
    if set(value) != {"migrated"}:
        return set(), [f"migration file must contain only migrated: {rel(path)}"]
    migrated = value.get("migrated")
    if not isinstance(migrated, list) or any(not isinstance(chapter_id, str) for chapter_id in migrated):
        return set(), [f"migration migrated must be a list of chapter IDs: {rel(path)}"]
    migrated_ids = set(migrated)
    errors: list[str] = []
    if len(migrated_ids) != len(migrated):
        errors.append(f"migration migrated must not contain duplicate chapter IDs: {rel(path)}")
    unknown = sorted(migrated_ids - set(CHAPTERS_BY_ID))
    if unknown:
        errors.append(f"migration has unknown chapter IDs: {', '.join(unknown)}")
    return migrated_ids, errors


def resolve_chapters(raw: list[str] | None) -> list[Path]:
    selected_tokens = raw if raw else [str(path) for path in DEFAULT_CHAPTERS]
    selected = [item.strip() for token in selected_tokens for item in token.split(",") if item.strip()]
    if not selected:
        raise SystemExit("--chapters must name at least one chapter")
    paths: list[Path] = []
    for item in selected:
        if item in CHAPTERS_BY_ID:
            paths.append((ROOT / CHAPTERS_BY_ID[item]).resolve())
            continue
        paths.append((ROOT / item).resolve() if not Path(item).is_absolute() else Path(item).resolve())
    for path in paths:
        if ROOT not in path.parents and path != ROOT:
            raise SystemExit(f"chapter path must stay inside project: {path}")
    if len(set(paths)) != len(paths):
        raise SystemExit("--chapters must not select a chapter more than once")
    return paths


def main() -> int:
    args = parse_args()
    migration_path = Path(args.migration)
    migration_path = migration_path if migration_path.is_absolute() else ROOT / migration_path
    migrated_ids, migration_errors = load_migrated_chapters(migration_path)
    audits = [audit_chapter(path, path.stem in migrated_ids) for path in resolve_chapters(args.chapters)]
    errors = migration_errors + [f"{audit.path}: {error}" for audit in audits for error in audit.errors]
    report = {
        "schemaVersion": 1,
        "kind": "textbook-apparatus-audit-report",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if not errors else "failed",
        "chapterCount": len(audits),
        "migration": {"path": str(rel(migration_path)), "migratedChapterIds": sorted(migrated_ids)},
        "chapters": [audit.__dict__ for audit in audits],
        "errors": errors,
    }
    if args.report:
        report_path = Path(args.report)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if errors:
        print(f"textbook apparatus audit failed: {len(errors)} issue(s)")
        for error in errors:
            print(f"- {error}")
        if args.report:
            print(f"report: {args.report}")
        return 1
    standard_count = sum(1 for audit in audits if Path(audit.path).stem in migrated_ids)
    print(
        f"textbook apparatus audit passed for {len(audits)} chapter(s) "
        f"(legacy rules: {len(audits) - standard_count}; standard rules: {standard_count})"
    )
    if args.report:
        print(f"report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
