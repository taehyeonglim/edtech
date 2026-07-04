#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

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
    parser.add_argument("--chapters", nargs="*", help="Specific chapter markdown paths to audit. Defaults to all 11 chapters.")
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


def audit_chapter(path: Path) -> ChapterAudit:
    errors: list[str] = []
    relative = rel(path)
    if not path.is_file():
        return ChapterAudit(str(relative), "failed", {}, ["chapter file is missing"])

    text = path.read_text(encoding="utf-8")
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


def resolve_chapters(raw: list[str] | None) -> list[Path]:
    selected = raw if raw else [str(path) for path in DEFAULT_CHAPTERS]
    paths = [(ROOT / item).resolve() if not Path(item).is_absolute() else Path(item).resolve() for item in selected]
    for path in paths:
        if ROOT not in path.parents and path != ROOT:
            raise SystemExit(f"chapter path must stay inside project: {path}")
    return paths


def main() -> int:
    args = parse_args()
    audits = [audit_chapter(path) for path in resolve_chapters(args.chapters)]
    errors = [f"{audit.path}: {error}" for audit in audits for error in audit.errors]
    report = {
        "schemaVersion": 1,
        "kind": "textbook-apparatus-audit-report",
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if not errors else "failed",
        "chapterCount": len(audits),
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
    print(f"textbook apparatus audit passed for {len(audits)} chapter(s)")
    if args.report:
        print(f"report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
