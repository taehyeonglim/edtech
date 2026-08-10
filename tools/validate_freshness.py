#!/usr/bin/env python3
"""Fail-closed freshness checks for policy, AI, and product textbook chapters."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
PRIVATE_MARKERS: Final = (
    "/" + "Users/",
    "file:" + "//",
    ".gjc/",
    "content" + "/chapters",
)
FORBIDDEN_POLICY_KEYS: Final = {
    "raw_evidence",
    "student_information",
    "internal_path",
    "release_instance",
}
DATE_FIELDS: Final = ("confirmed_date", "review_date")
REQUIRED_POLICY_KEYS: Final = {
    "version",
    "scope",
    "required_front_matter",
    "review_cadence",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail-closed freshness checks for policy, AI, and product chapters."
    )
    parser.add_argument("--as-of", metavar="YYYY-MM-DD", help="Date used for freshness evaluation.")
    parser.add_argument("--fixture", metavar="PATH", help="Validate Markdown chapters under PATH instead of docs.")
    parser.add_argument("--policy", default="quality/freshness-policy.yml")
    return parser.parse_args()


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def nested_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for item in value.values():
            keys.update(nested_keys(item))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for item in value:
            keys.update(nested_keys(item))
        return keys
    return set()


def load_policy(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        text = path.read_text(encoding="utf-8")
        policy = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"freshness policy is unreadable or invalid YAML/JSON: {exc}"]
    if not isinstance(policy, dict):
        return None, ["freshness policy must be a mapping"]
    return policy, []


def validate_policy(policy: dict[str, Any], policy_text: str) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    if set(policy) != REQUIRED_POLICY_KEYS:
        errors.append("freshness policy must contain only version, scope, required_front_matter, and review_cadence")
    if policy.get("version") != 1:
        errors.append("freshness policy version must be 1")
    forbidden = nested_keys(policy) & FORBIDDEN_POLICY_KEYS
    if forbidden:
        errors.append(f"freshness policy contains prohibited ownership keys: {sorted(forbidden)}")
    for marker in PRIVATE_MARKERS:
        if marker in policy_text:
            errors.append(f"freshness policy contains prohibited public marker: {marker}")

    scope = policy.get("scope")
    if not isinstance(scope, dict) or set(scope) != {"topic_terms"}:
        errors.append("freshness policy scope must contain only topic_terms")
    elif not isinstance(scope["topic_terms"], list) or not scope["topic_terms"] or any(
        not isinstance(term, str) or not term for term in scope["topic_terms"]
    ):
        errors.append("freshness policy topic_terms must be a non-empty list of strings")

    fields = policy.get("required_front_matter")
    if not isinstance(fields, dict) or fields != {field: field for field in (*DATE_FIELDS, "review_cadence_days")}:
        errors.append("freshness policy must require confirmed_date, review_date, and review_cadence_days front matter")

    cadence = policy.get("review_cadence")
    if not isinstance(cadence, dict) or set(cadence) != {"minimum_days", "maximum_days"}:
        errors.append("freshness policy review_cadence must contain only minimum_days and maximum_days")
    elif (
        not isinstance(cadence["minimum_days"], int)
        or isinstance(cadence["minimum_days"], bool)
        or not isinstance(cadence["maximum_days"], int)
        or isinstance(cadence["maximum_days"], bool)
        or cadence["minimum_days"] < 1
        or cadence["minimum_days"] > cadence["maximum_days"]
    ):
        errors.append("freshness policy review cadence bounds must be positive ordered integers")

    return (policy if not errors else None), errors


def parse_front_matter(text: str, label: str) -> tuple[dict[str, str] | None, list[str]]:
    if not text.startswith("---\n"):
        return None, [f"{label}: missing YAML front matter"]
    end = text.find("\n---", 4)
    if end == -1:
        return None, [f"{label}: front matter is not closed"]
    values: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if not line or line.lstrip().startswith("#") or line[0].isspace():
            continue
        match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_]*)\s*:\s*(.*?)\s*", line)
        if not match:
            return None, [f"{label}: invalid top-level front matter field"]
        key, value = match.groups()
        if key in values:
            return None, [f"{label}: duplicate front matter field {key}"]
        values[key] = value.strip("\"'")
    return values, []


def parse_iso_date(value: str, field: str, label: str) -> tuple[date | None, list[str]]:
    try:
        return date.fromisoformat(value), []
    except ValueError:
        return None, [f"{label}: {field} must be an ISO date (YYYY-MM-DD)"]




def validate_chapter(path: Path, policy: dict[str, Any], as_of: date, root: Path) -> list[str]:
    label = path.relative_to(root).as_posix()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{label}: unreadable chapter: {exc}"]
    front_matter, errors = parse_front_matter(text, label)
    if front_matter is None:
        return errors
    declared = [field for field in policy["required_front_matter"] if field in front_matter]
    if not declared:
        return []
    missing = [field for field in policy["required_front_matter"] if not front_matter.get(field)]
    if missing:
        return [f"{label}: missing required freshness front matter: {', '.join(missing)}"]

    confirmed, confirmed_errors = parse_iso_date(front_matter["confirmed_date"], "confirmed_date", label)
    reviewed, review_errors = parse_iso_date(front_matter["review_date"], "review_date", label)
    errors.extend(confirmed_errors)
    errors.extend(review_errors)
    try:
        cadence = int(front_matter["review_cadence_days"])
    except ValueError:
        errors.append(f"{label}: review_cadence_days must be an integer")
        cadence = 0
    minimum = policy["review_cadence"]["minimum_days"]
    maximum = policy["review_cadence"]["maximum_days"]
    if cadence < minimum or cadence > maximum:
        errors.append(f"{label}: review_cadence_days must be between {minimum} and {maximum}")
    if "review_targets" in front_matter and cadence > 180:
        errors.append(f"{label}: review_targets require review_cadence_days to be at most 180")
    if errors:
        return errors
    assert confirmed is not None and reviewed is not None
    if confirmed > as_of:
        errors.append(f"{label}: confirmed_date cannot be later than --as-of")
    if reviewed > as_of:
        errors.append(f"{label}: review_date cannot be later than --as-of")
    if reviewed < confirmed:
        errors.append(f"{label}: review_date cannot be earlier than confirmed_date")
    if as_of > reviewed + timedelta(days=cadence):
        errors.append(f"{label}: review expired on {(reviewed + timedelta(days=cadence)).isoformat()}; update review_date")
    return errors


def main() -> int:
    args = parse_args()
    try:
        as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    except ValueError:
        print("ERROR: --as-of must be an ISO date (YYYY-MM-DD)")
        return 2

    policy_path = resolve_path(args.policy)
    policy, errors = load_policy(policy_path)
    if policy is not None:
        try:
            policy_text = policy_path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"freshness policy is unreadable: {exc}")
        else:
            policy, policy_errors = validate_policy(policy, policy_text)
            errors.extend(policy_errors)
    root = resolve_path(args.fixture) if args.fixture else ROOT / "docs"
    if not root.is_dir():
        errors.append(f"chapter directory is missing or not a directory: {root}")
    elif policy is not None:
        chapters = sorted(root.rglob("*.md")) if args.fixture else sorted(root.glob("part*/ch*.md"))
        if not chapters:
            errors.append(f"no Markdown chapters found under {root}")
        for chapter in chapters:
            errors.extend(validate_chapter(chapter, policy, as_of, root))
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"Freshness policy is valid as of {as_of.isoformat()}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
