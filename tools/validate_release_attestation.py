#!/usr/bin/env python3
"""Fail-closed validation of public release-attestation policy and bindings."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
SAFE_VALUE = re.compile(r"^[A-Za-z0-9._-]+$")
RUN_VALUE = re.compile(r"^[1-9][0-9]*$")
ROLE_AGGREGATE = re.compile(r"^[1-9][0-9]*$")
FORBIDDEN_POLICY_KEYS = {
    "source_sha", "source_digest", "run_id", "run_attempt", "artifact_id",
    "artifact_name", "artifact_digest", "evidence_locator", "reviewer_identity",
    "reviewer", "raw_evidence", "student_information", "internal_path", "release_instance",
}
POLICY_KEYS = {"version", "release_gate", "artifact"}
PRE_KEYS = {
    "source_digest", "evidence_manifest_digest", "evidence_role_aggregate",
    "candidate_digest", "policy_digest", "run_id", "run_attempt", "expected_artifact_name",
}
POST_KEYS = PRE_KEYS | {"returned_artifact_id", "platform_artifact_digest", "artifact_api_metadata"}


def resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def scalar(value: str) -> Any:
    if value in {"true", "false"}:
        return value == "true"
    if re.fullmatch(r"[0-9]+", value):
        return int(value)
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def load_policy(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return None, [f"policy is unreadable: {exc}"]
    result: dict[str, Any] = {}
    section: str | None = None
    list_key: str | None = None
    for number, raw in enumerate(lines, 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if "\t" in raw or raw.rstrip() != raw:
            return None, [f"policy line {number} uses unsupported whitespace"]
        indent = len(raw) - len(raw.lstrip(" "))
        text = raw.strip()
        if indent == 0:
            if ":" not in text:
                return None, [f"policy line {number} is invalid"]
            key, value = text.split(":", 1)
            if not key:
                return None, [f"policy line {number} has an empty key"]
            if value.strip() == "":
                result[key] = {}
                section, list_key = key, None
            else:
                result[key] = scalar(value.strip())
                section, list_key = None, None
        elif indent == 2 and section is not None:
            if text.startswith("- "):
                if list_key is None:
                    return None, [f"policy line {number} has a list without a key"]
                result[section][list_key].append(scalar(text[2:]))
                continue
            if ":" not in text:
                return None, [f"policy line {number} is invalid"]
            key, value = text.split(":", 1)
            if value.strip() == "":
                result[section][key] = []
                list_key = key
            else:
                result[section][key] = scalar(value.strip())
                list_key = None
        elif indent == 4 and text.startswith("- ") and section is not None and list_key is not None:
            result[section][list_key].append(scalar(text[2:]))
        else:
            return None, [f"policy line {number} has unsupported structure"]
    return result, []


def nested_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(nested_keys(item) for item in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(nested_keys(item) for item in value) if value else [])
    return set()


def validate_policy(policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    forbidden = nested_keys(policy) & FORBIDDEN_POLICY_KEYS
    if forbidden:
        errors.append(f"policy contains release-instance keys: {sorted(forbidden)}")
    if set(policy) != POLICY_KEYS or policy.get("version") != 1:
        errors.append("policy must contain only version, release_gate, and artifact with version 1")
    gate = policy.get("release_gate")
    if not isinstance(gate, dict) or gate.get("applies_to") != "all-domains" or gate.get("blocked_severities") != ["critical", "serious"] or set(gate) != {"applies_to", "blocked_severities"}:
        errors.append("release_gate must block critical and serious in all domains")
    artifact = policy.get("artifact")
    expected = {"name_prefix", "digest_algorithm"}
    if not isinstance(artifact, dict) or set(artifact) != expected or artifact.get("name_prefix") != "github-pages-" or artifact.get("digest_algorithm") != "sha256":
        errors.append("artifact policy must define the github-pages run name and sha256 only")
    return errors


def load_json(path: Path, label: str) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"{label} is unreadable or invalid JSON: {exc}"]
    return (value, []) if isinstance(value, dict) else (None, [f"{label} must be a JSON object"])


def expected_name(policy: dict[str, Any], run_id: str, run_attempt: str) -> str:
    return f"{policy['artifact']['name_prefix']}{run_id}-{run_attempt}"


def validate_pre(binding: dict[str, Any], policy: dict[str, Any], policy_path: Path) -> list[str]:
    errors: list[str] = []
    if set(binding) != PRE_KEYS:
        return ["pre-upload binding must contain exactly source/evidence/candidate/policy digests, role aggregate, run context, and expected_artifact_name"]
    for key in ("source_digest", "evidence_manifest_digest", "candidate_digest", "policy_digest"):
        if not isinstance(binding[key], str) or not DIGEST.fullmatch(binding[key]):
            errors.append(f"{key} must be a sha256 digest")
    if not isinstance(binding["evidence_role_aggregate"], str) or not ROLE_AGGREGATE.fullmatch(binding["evidence_role_aggregate"]):
        errors.append("evidence_role_aggregate must be a non-zero coarse role count")
    for key in ("run_id", "run_attempt"):
        if not isinstance(binding[key], str) or not RUN_VALUE.fullmatch(binding[key]):
            errors.append(f"{key} must be a positive decimal identifier")
    actual_policy = "sha256:" + hashlib.sha256(policy_path.read_bytes()).hexdigest()
    if binding.get("policy_digest") != actual_policy:
        errors.append("policy_digest does not match the current tracked policy")
    if binding.get("expected_artifact_name") != expected_name(policy, binding.get("run_id", ""), binding.get("run_attempt", "")):
        errors.append("expected_artifact_name is not deterministic for the current run context")
    return errors


def validate_post(binding: dict[str, Any], policy: dict[str, Any], policy_path: Path) -> list[str]:
    errors = validate_pre({key: value for key, value in binding.items() if key in PRE_KEYS}, policy, policy_path)
    if set(binding) != POST_KEYS:
        return errors + ["post-upload binding contains unsupported fields"]
    returned = binding.get("returned_artifact_id")
    platform_digest = binding.get("platform_artifact_digest")
    metadata = binding.get("artifact_api_metadata")
    if not isinstance(returned, str) or not RUN_VALUE.fullmatch(returned):
        errors.append("returned_artifact_id must be a positive decimal identifier")
    if not isinstance(platform_digest, str) or not DIGEST.fullmatch(platform_digest):
        errors.append("platform_artifact_digest must be a sha256 digest")
    expected = {"id", "name", "run_id", "run_attempt", "expired", "digest"}
    if not isinstance(metadata, dict) or set(metadata) != expected:
        return errors + ["Artifact API metadata has unsupported fields"]
    if (metadata.get("id") != returned or metadata.get("run_id") != binding.get("run_id") or
            metadata.get("run_attempt") != binding.get("run_attempt") or
            metadata.get("name") != binding.get("expected_artifact_name") or
            metadata.get("expired") is not False or metadata.get("digest") != platform_digest):
        errors.append("Artifact API metadata does not exactly match the current release binding")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate fail-closed release attestation boundaries.")
    parser.add_argument("--phase", required=True, choices=("policy", "pre-upload", "post-upload"))
    parser.add_argument("--policy", default="quality/release-attestation.yml")
    parser.add_argument("--binding", help="Untracked release binding JSON, required outside policy phase")
    args = parser.parse_args()
    policy_path = resolve(args.policy)
    policy, errors = load_policy(policy_path)
    if policy is not None:
        errors.extend(validate_policy(policy))
    if args.phase != "policy":
        if not args.binding:
            errors.append("--binding is required for this phase")
        else:
            binding, binding_errors = load_json(resolve(args.binding), "binding")
            errors.extend(binding_errors)
            if binding is not None and policy is not None:
                errors.extend(validate_pre(binding, policy, policy_path) if args.phase == "pre-upload" else validate_post(binding, policy, policy_path))
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"Release attestation {args.phase} validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
