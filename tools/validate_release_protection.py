#!/usr/bin/env python3
"""Fail-closed validation of the repository's protected release boundary."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_CODEOWNERS = {
    "/.github/workflows/**", "/quality/**", "/tools/**", "/package.json",
    "/package-lock.json", "/requirements*.txt", "/constraints*.txt",
    "/poetry.lock", "/Pipfile.lock",
}
MANAGER_PERMISSIONS = {"admin", "maintain"}


def load_json(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"input is unreadable or invalid JSON: {exc}"]
    return (value, []) if isinstance(value, dict) else (None, ["input must be a JSON object"])


def parse_codeowners(path: Path) -> tuple[dict[str, list[str]], list[str]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return {}, [f"CODEOWNERS is unreadable: {exc}"]
    entries: dict[str, list[str]] = {}
    for raw in lines:
        parts = raw.split("#", 1)[0].split()
        if not parts:
            continue
        if len(parts) < 2 or not all(owner.startswith("@") for owner in parts[1:]):
            return {}, ["CODEOWNERS contains an invalid ownership entry"]
        entries[parts[0]] = parts[1:]
    return entries, []


def reviewer_key(reviewer: Any) -> str | None:
    if not isinstance(reviewer, dict) or reviewer.get("type") not in {"User", "Team"}:
        return None
    identity = reviewer.get("reviewer")
    if not isinstance(identity, dict):
        return None
    if reviewer["type"] == "User" and isinstance(identity.get("login"), str):
        return "@" + identity["login"]
    organization, slug = identity.get("organization"), identity.get("slug")
    org_login = organization.get("login") if isinstance(organization, dict) else None
    if reviewer["type"] == "Team" and isinstance(org_login, str) and isinstance(slug, str):
        return f"@{org_login}/{slug}"
    return None


def api_json(repository: str, token: str) -> tuple[dict[str, Any] | None, list[str]]:
    """Fetch required metadata only; exceptions and output never include the token."""
    if repository.count("/") != 1 or any(not part for part in repository.split("/")):
        return None, ["--repository must be owner/repository"]

    def get(path: str) -> Any:
        request = Request(f"https://api.github.com/repos/{repository}{path}", headers={
            "Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}",
        })
        with urlopen(request, timeout=15) as response:  # nosec B310: fixed GitHub API origin
            return json.loads(response.read().decode("utf-8"))

    try:
        try:
            protection = get("/branches/main/protection")
        except HTTPError as exc:
            if exc.code != 404:
                raise
            protection = None
        rulesets = get("/rulesets?includes_parents=false")
        environment = get("/environments/github-pages")
        teams = get("/teams?per_page=100")
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        return None, [f"GitHub API release-protection lookup failed: {getattr(exc, 'code', type(exc).__name__)}"]
    codeowners, errors = parse_codeowners(ROOT / ".github/CODEOWNERS")
    if errors:
        return None, errors
    permissions: dict[str, str] = {}
    reviewers = environment.get("protection_rules", []) if isinstance(environment, dict) else []
    for rule in reviewers:
        for reviewer in rule.get("reviewers", []) if isinstance(rule, dict) else []:
            key = reviewer_key(reviewer)
            if not key:
                continue
            if reviewer.get("type") == "User":
                try:
                    response = get(f"/collaborators/{quote(key[1:], safe='')}/permission")
                except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
                    return None, [f"GitHub API reviewer-permission lookup failed: {getattr(exc, 'code', type(exc).__name__)}"]
                permissions[key] = response.get("permission") if isinstance(response, dict) else ""
            else:
                matching = [team for team in teams if isinstance(team, dict) and f"@{team.get('organization', {}).get('login')}/{team.get('slug')}" == key]
                if len(matching) != 1:
                    return None, ["GitHub API reviewer team permission lookup failed"]
                permissions[key] = matching[0].get("permission")
    return {"branch_protection": protection, "rulesets": rulesets, "environment": environment,
            "codeowners": codeowners, "reviewer_permissions": permissions}, []


def pr_reviews_enabled(value: Any) -> bool:
    return isinstance(value, dict) and isinstance(value.get("required_approving_review_count"), int) and value["required_approving_review_count"] >= 1 and value.get("require_code_owner_reviews") is True


def ruleset_protects_main(ruleset: Any) -> bool:
    if not isinstance(ruleset, dict) or ruleset.get("enforcement") != "active":
        return False
    conditions = ruleset.get("conditions")
    ref_name = conditions.get("ref_name") if isinstance(conditions, dict) else None
    includes = ref_name.get("include") if isinstance(ref_name, dict) else None
    if not isinstance(includes, list) or not any(item in {"main", "refs/heads/main", "~DEFAULT_BRANCH"} for item in includes):
        return False
    return any(isinstance(rule, dict) and rule.get("type") == "pull_request" and pr_reviews_enabled(rule.get("parameters")) for rule in ruleset.get("rules", []))


def required_manager_reviewer(environment: Any, allowed: set[str], permissions: Any) -> bool:
    if not isinstance(environment, dict) or environment.get("prevent_self_review") is not True or not isinstance(permissions, dict):
        return False
    found = False
    rules = environment.get("protection_rules")
    if not isinstance(rules, list):
        return False
    for rule in rules:
        if not isinstance(rule, dict) or rule.get("type") != "required_reviewers":
            continue
        reviewers = rule.get("reviewers")
        if not isinstance(reviewers, list):
            return False
        for reviewer in reviewers:
            key = reviewer_key(reviewer)
            if not key or key not in allowed or permissions.get(key) not in MANAGER_PERMISSIONS:
                return False
            found = True
    return found


def validate(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    protection, rulesets = data.get("branch_protection"), data.get("rulesets")
    protected = isinstance(protection, dict) and pr_reviews_enabled(protection.get("required_pull_request_reviews"))
    protected = protected or (isinstance(rulesets, list) and any(ruleset_protects_main(rule) for rule in rulesets))
    if not protected:
        errors.append("main must require an approving CODEOWNERS pull-request review through branch protection or an active ruleset")
    codeowners = data.get("codeowners")
    if not isinstance(codeowners, dict):
        errors.append("CODEOWNERS data is required")
        allowed: set[str] = set()
    else:
        missing = sorted(pattern for pattern in REQUIRED_CODEOWNERS if not isinstance(codeowners.get(pattern), list) or not codeowners[pattern])
        if missing:
            errors.append(f"CODEOWNERS must assign repository administrators to: {', '.join(missing)}")
        allowed = set().union(*(set(codeowners.get(pattern, [])) for pattern in REQUIRED_CODEOWNERS))
    if not required_manager_reviewer(data.get("environment"), allowed, data.get("reviewer_permissions")):
        errors.append("github-pages must require only allowed CODEOWNERS managers with admin or maintain permission and prevent self-review")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate fail-closed GitHub release protection.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture")
    source.add_argument("--repository", help="GitHub owner/repository; requires --token or GITHUB_TOKEN")
    parser.add_argument("--token", help="GitHub API token; never printed")
    args = parser.parse_args()
    if args.fixture:
        if args.token:
            print("ERROR: --token is only valid with --repository")
            return 1
        data, errors = load_json(Path(args.fixture))
    else:
        token = args.token or os.environ.get("GITHUB_TOKEN")
        if not token:
            print("ERROR: --repository requires --token or GITHUB_TOKEN")
            return 1
        data, errors = api_json(args.repository, token)
    if data is not None:
        errors.extend(validate(data))
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Release protection validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
