#!/usr/bin/env python3
"""Fail-closed validation for the public textbook-to-lecture quality contract."""
from __future__ import annotations

import argparse
from datetime import date
import re
import sys
from pathlib import Path
from typing import Any, Final

try:
    import yaml
except ImportError as exc:  # pragma: no cover - supplied by the existing MkDocs dependency set
    raise SystemExit("PyYAML is required by this repository's validation tools") from exc

ROOT: Final = Path(__file__).resolve().parents[1]
CHAPTER_IDS: Final = {f"ch{number:02d}" for number in range(1, 12)}
LECTURE_IDS: Final = {f"lecture-{number:02d}" for number in range(1, 11)}
RUBRIC_DIMENSIONS: Final = {"learning-objective-alignment", "conceptual-accuracy", "instructional-coherence", "learner-accessibility", "assessment-evidence"}
SEVERITIES: Final = ("critical", "serious", "moderate", "minor")
LOCAL_ID_FIELDS: Final = ("objectives", "activity_ids", "assessment_ids")
REQUIRED_FRONT_MATTER_KEYS: Final = {"chapter_id", "objectives", "activity_ids", "assessment_ids", "source_ids", "prework_minutes", "confirmed_date", "review_date", "review_cadence_days"}
OPTIONAL_FRONT_MATTER_KEYS: Final = {"review_targets"}
PRIVATE_MARKERS: Final = ("/" + "Users/", "Previous_lecture" + "_content", "content" + "/chapters", "file:" + "//")
FORBIDDEN_CONTRACT_KEYS: Final = {"chapter_metadata", "chapters", "release_instance", "raw_evidence", "student_information", "internal_path"}


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an ISO date (YYYY-MM-DD)") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate textbook lecture alignment and quality policy.")
    parser.add_argument("--contract", default="quality/textbook-contract.yml")
    parser.add_argument("--severity-policy", default="quality/severity-policy.yml")
    parser.add_argument("--chapters-index", default="chapters/index.html")
    parser.add_argument("--docs-dir", default="docs")
    parser.add_argument("--as-of", type=parse_date, default=date.today(), help="ISO date used to reject future review dates")
    return parser.parse_args()


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def load_yaml(path: Path, label: str) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return None, [f"{label} is unreadable or invalid YAML: {exc}"]
    if not isinstance(value, dict):
        return None, [f"{label} must be a YAML mapping"]
    return value, []


def nested_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(nested_keys(item) for item in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(nested_keys(item) for item in value)) if value else set()
    return set()


def check_public_content(path: Path, label: str) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return [f"{label} contains prohibited public marker: {marker}" for marker in PRIVATE_MARKERS if marker in text]


def validate_contract(contract: dict[str, Any]) -> tuple[set[tuple[str, str]], list[str]]:
    errors: list[str] = []
    if set(contract) - {"version", "rubric", "edges", "text_only_chapter_ids"}:
        errors.append(f"contract has unsupported keys: {sorted(set(contract) - {'version', 'rubric', 'edges', 'text_only_chapter_ids'})}")
    forbidden = nested_keys(contract) & FORBIDDEN_CONTRACT_KEYS
    if forbidden:
        errors.append(f"contract contains prohibited ownership keys: {sorted(forbidden)}")
    if contract.get("version") != 1:
        errors.append("contract version must be 1")
    rubric = contract.get("rubric")
    if not isinstance(rubric, dict) or set(rubric) != {"dimensions"} or not isinstance(rubric.get("dimensions"), list):
        errors.append("contract rubric must contain only dimensions")
    elif any(not isinstance(dimension, str) for dimension in rubric["dimensions"]):
        errors.append("contract rubric dimensions must be a list of strings")
    elif len(rubric["dimensions"]) != 5 or len(set(rubric["dimensions"])) != 5 or set(rubric["dimensions"]) != RUBRIC_DIMENSIONS:
        errors.append("contract rubric must define the five shared quality dimensions exactly once")
    pairs: set[tuple[str, str]] = set()
    edges = contract.get("edges")
    if not isinstance(edges, list):
        errors.append("contract edges must be a list")
    else:
        for index, edge in enumerate(edges, 1):
            if not isinstance(edge, dict) or set(edge) != {"lecture_id", "chapter_id"} or not all(isinstance(edge.get(key), str) for key in ("lecture_id", "chapter_id")):
                errors.append(f"contract edge {index} must contain only string lecture_id and chapter_id")
                continue
            pair = (edge["lecture_id"], edge["chapter_id"])
            if pair in pairs:
                errors.append(f"duplicate contract edge: {pair[0]} -> {pair[1]}")
            pairs.add(pair)
            if pair[0] not in LECTURE_IDS:
                errors.append(f"orphan lecture ID: {pair[0]}")
            if pair[1] not in CHAPTER_IDS:
                errors.append(f"orphan chapter ID: {pair[1]}")
    text_only = contract.get("text_only_chapter_ids")
    if not isinstance(text_only, list) or any(not isinstance(item, str) for item in text_only):
        errors.append("text_only_chapter_ids must be a list of strings")
        text_only_ids: set[str] = set()
    else:
        text_only_ids = set(text_only)
        if len(text_only) != len(text_only_ids):
            errors.append("text_only_chapter_ids must not contain duplicates")
        if text_only_ids - CHAPTER_IDS:
            errors.append(f"orphan text-only chapter IDs: {sorted(text_only_ids - CHAPTER_IDS)}")
    edge_chapters = {chapter for _, chapter in pairs if chapter in CHAPTER_IDS}
    if edge_chapters & text_only_ids:
        errors.append("a text-only chapter must not have a lecture edge")
    if edge_chapters | text_only_ids != CHAPTER_IDS:
        errors.append("contract must cover all chapters ch01 through ch11 exactly as edge-backed or text-only")
    if {lecture for lecture, _ in pairs if lecture in LECTURE_IDS} != LECTURE_IDS:
        errors.append("contract must map all ten lectures lecture-01 through lecture-10")
    return pairs, errors


def validate_policy(policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(policy) != {"version", "severity_levels", "release_gate"}:
        errors.append("severity policy must contain only version, severity_levels, and release_gate")
    if policy.get("version") != 1:
        errors.append("severity policy version must be 1")
    levels = policy.get("severity_levels")
    if not isinstance(levels, dict) or set(levels) != set(SEVERITIES):
        errors.append("severity policy must define exactly critical, serious, moderate, and minor")
    else:
        for severity in SEVERITIES:
            if not isinstance(levels[severity], dict) or set(levels[severity]) != {"release_blocking"} or not isinstance(levels[severity]["release_blocking"], bool):
                errors.append(f"severity level {severity} must define boolean release_blocking only")
        if levels.get("critical", {}).get("release_blocking") is not True or levels.get("serious", {}).get("release_blocking") is not True:
            errors.append("critical and serious must block release")
        if levels.get("moderate", {}).get("release_blocking") is not False or levels.get("minor", {}).get("release_blocking") is not False:
            errors.append("moderate and minor must not block release")
    gate = policy.get("release_gate")
    if not isinstance(gate, dict) or set(gate) != {"applies_to", "blocked_severities"}:
        errors.append("release_gate must contain only applies_to and blocked_severities")
    elif gate.get("applies_to") != "all-domains" or gate.get("blocked_severities") != ["critical", "serious"]:
        errors.append("release_gate must block critical and serious in all-domains")
    return errors


def split_front_matter(text: str, label: str) -> tuple[dict[str, Any] | None, str, list[str]]:
    match = re.match(r"\A---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        return None, text, [f"{label} must start with YAML front matter"]
    try:
        metadata = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        return None, text[match.end():], [f"{label} front matter is invalid YAML: {exc}"]
    if not isinstance(metadata, dict):
        return None, text[match.end():], [f"{label} front matter must be a mapping"]
    return metadata, text[match.end():], []


def table_section(body: str) -> str:
    tables = re.findall(r"(?:^\|.*\|\n)+", body, re.MULTILINE)
    return "\n".join(table for table in tables if re.search(r"^\|.*(?:학습목표|목표 ID).*\|$", table, re.MULTILINE))


def section(body: str, heading_pattern: str) -> str:
    match = re.search(rf"^##\s+{heading_pattern}[ \t]*$([\s\S]*?)(?=^##\s|\Z)", body, re.MULTILINE)
    return match.group(1) if match else ""


def exact_token_present(token: str, text: str) -> bool:
    return bool(re.search(rf"(?<![A-Za-z0-9_-]){re.escape(token)}(?![A-Za-z0-9_-])", text))


def source_is_mapped(source_id: str, correspondence: str, body: str) -> bool:
    for line in correspondence.splitlines():
        if not exact_token_present(source_id, line):
            continue
        for footnote_id in re.findall(r"\[\^([^\]]+)\]", line):
            if re.search(rf"^\[\^{re.escape(footnote_id)}\]:", body, re.MULTILINE):
                return True
    return False


def body_resolves_id(field: str, value: str, body: str) -> bool:
    if field == "source_ids":
        return exact_token_present(value, body)
    return exact_token_present(value, body)


def validate_local_ids(metadata: dict[str, Any], body: str, chapter_id: str, label: str) -> list[str]:
    errors: list[str] = []
    for field in LOCAL_ID_FIELDS + ("source_ids",):
        values = metadata.get(field)
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            errors.append(f"{label} {field} must be a list of strings, not mixed objects and strings")
            continue
        if len(values) != len(set(values)):
            errors.append(f"{label} {field} contains duplicate IDs")
        if field != "source_ids" and any(not value.startswith(f"{chapter_id}-") for value in values):
            errors.append(f"{label} {field} IDs must use the {chapter_id}- prefix")
        for value in values:
            if not body_resolves_id(field, value, body):
                errors.append(f"{label} orphan local ID outside front matter: {value}")
    return errors


def learning_objective_count(body: str) -> int:
    heading = re.search(r"^##\s+학습 목표\s*$", body, re.MULTILINE)
    if not heading:
        return -1
    following = re.search(r"^##\s+", body[heading.end():], re.MULTILINE)
    section = body[heading.end() : heading.end() + following.start()] if following else body[heading.end():]
    return len(re.findall(r"^\s*\d+\.\s+", section, re.MULTILINE))


def validate_chapter_front_matter(path: Path, expected_id: str, as_of: date) -> list[str]:
    label = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{label} is unreadable: {exc}"]
    metadata, body, errors = split_front_matter(text, label)
    if metadata is None:
        return errors
    unknown = set(metadata) - REQUIRED_FRONT_MATTER_KEYS - OPTIONAL_FRONT_MATTER_KEYS
    missing = REQUIRED_FRONT_MATTER_KEYS - set(metadata)
    if missing:
        errors.append(f"{label} front matter missing keys: {sorted(missing)}")
    if unknown:
        errors.append(f"{label} front matter has unsupported keys: {sorted(unknown)}")
    chapter_id = metadata.get("chapter_id")
    if not isinstance(chapter_id, str) or chapter_id != expected_id:
        errors.append(f"{label} chapter_id must be scalar {expected_id}")
        return errors
    errors.extend(validate_local_ids(metadata, body, chapter_id, label))
    minutes = metadata.get("prework_minutes")
    if isinstance(minutes, bool) or not isinstance(minutes, int) or not 30 <= minutes <= 45:
        errors.append(f"{label} prework_minutes must be an integer from 30 through 45")
    cadence = metadata.get("review_cadence_days")
    if isinstance(cadence, bool) or not isinstance(cadence, int) or cadence <= 0:
        errors.append(f"{label} review_cadence_days must be a positive integer")
    for field in ("confirmed_date", "review_date"):
        value = metadata.get(field)
        parsed = value if isinstance(value, date) and not isinstance(value, str) else None
        if parsed is None and isinstance(value, str):
            try:
                parsed = date.fromisoformat(value)
            except ValueError:
                pass
        if parsed is None:
            errors.append(f"{label} {field} must be an ISO date")
        elif field == "review_date" and parsed > as_of:
            errors.append(f"{label} review_date must not be in the future")
    objectives = metadata.get("objectives")
    if isinstance(objectives, list) and all(isinstance(item, str) for item in objectives):
        count = learning_objective_count(body)
        if count < 0:
            errors.append(f"{label} is missing the 학습 목표 section")
        elif count != len(objectives):
            errors.append(f"{label} front matter objectives ({len(objectives)}) must match body learning objectives ({count})")
        for objective_id in objectives:
            if body.count(objective_id) < 1:
                errors.append(f"{label} objective ID is missing from the objective correspondence table: {objective_id}")
    return errors


def source_edges(chapters_index: Path, docs_dir: Path, as_of: date) -> tuple[set[tuple[str, str]], list[str]]:
    errors: list[str] = []
    try:
        index = chapters_index.read_text(encoding="utf-8")
    except OSError as exc:
        return set(), [f"chapters index is unreadable: {exc}"]
    pairs: set[tuple[str, str]] = set()
    for card in re.findall(r'<li class="lecture-card">(.*?)</li>', index, re.DOTALL):
        week = re.search(r'<span class="week">(\d{2})</span>', card)
        if week:
            pairs.update((f"lecture-{week.group(1)}", f"ch{number}") for number in re.findall(r'\.\./book/part\d+/ch(\d{2})/', card))
    if {lecture for lecture, _ in pairs} != LECTURE_IDS:
        errors.append("chapters/index.html must expose textbook links for all ten lectures")
    doc_pairs: set[tuple[str, str]] = set()
    for chapter_id in sorted(CHAPTER_IDS):
        matches = list(docs_dir.rglob(f"{chapter_id}.md"))
        if len(matches) != 1:
            errors.append(f"docs must contain exactly one source file for {chapter_id}")
            continue
        path = matches[0]
        errors.extend(validate_chapter_front_matter(path, chapter_id, as_of))
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        doc_pairs.update((f"lecture-{number}", chapter_id) for number in re.findall(r'chapters/chapter-(\d{2})/slides/deck\.html', text))
    if doc_pairs != pairs:
        errors.append("docs lecture links must exactly match chapters/index.html textbook links")
    return pairs, errors


def validate_fixture_docs(contract_path: Path, as_of: date) -> list[str]:
    """Fixture docs are additional focused cases; contract-only fixtures use repository docs."""
    fixture_docs = contract_path.parent / "docs"
    if not fixture_docs.is_dir():
        return []
    errors: list[str] = []
    for path in sorted(fixture_docs.rglob("ch*.md")):
        errors.extend(validate_chapter_front_matter(path, path.stem, as_of))
    return errors


def main() -> int:
    args = parse_args()
    contract_path, policy_path = resolve_path(args.contract), resolve_path(args.severity_policy)
    contract, errors = load_yaml(contract_path, "contract")
    policy, policy_errors = load_yaml(policy_path, "severity policy")
    errors.extend(policy_errors + check_public_content(contract_path, "contract") + check_public_content(policy_path, "severity policy"))
    pairs: set[tuple[str, str]] = set()
    if contract is not None:
        pairs, contract_errors = validate_contract(contract)
        errors.extend(contract_errors)
    if policy is not None:
        errors.extend(validate_policy(policy))
    errors.extend(validate_fixture_docs(contract_path, args.as_of))
    source_pairs, source_errors = source_edges(resolve_path(args.chapters_index), resolve_path(args.docs_dir), args.as_of)
    errors.extend(source_errors)
    if contract is not None and pairs != source_pairs:
        errors.append("contract edges must exactly match public lecture and docs links")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Textbook alignment contract, chapter front matter, and severity policy are valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
