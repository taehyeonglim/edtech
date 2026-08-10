#!/usr/bin/env python3
"""Validate a candidate's public route list against the approved route manifest."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "quality/route-manifest.json"
LOCALHOSTS = {"localhost", "127.0.0.1", "::1"}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request: Request, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        return None


def load_routes(path: Path, label: str) -> tuple[list[str] | None, list[str]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"{label} is unreadable or invalid JSON: {exc}"]
    if not isinstance(value, dict) or set(value) != {"routes"}:
        return None, [f"{label} must be an object with only a routes array"]
    routes = value["routes"]
    if not isinstance(routes, list) or not all(isinstance(route, str) for route in routes):
        return None, [f"{label}.routes must be an array of strings"]
    malformed = [route for route in routes if not route.startswith("/") or "?" in route or "#" in route]
    if malformed:
        return None, [f"{label} contains malformed public routes: {', '.join(malformed)}"]
    return routes, []


def compare_routes(expected: list[str], candidate: list[str]) -> list[str]:
    errors: list[str] = []
    for route, count in sorted(Counter(expected).items()):
        if count > 1:
            errors.append(f"manifest contains duplicate route: {route}")
    for route, count in sorted(Counter(candidate).items()):
        if count > 1:
            errors.append(f"candidate contains duplicate route: {route}")
    expected_set = set(expected)
    candidate_set = set(candidate)
    for route in sorted(expected_set - candidate_set):
        errors.append(f"candidate missing route: {route}")
    for route in sorted(candidate_set - expected_set):
        errors.append(f"candidate has unexpected route: {route}")
    return errors


def validate_base_url(base_url: str) -> tuple[str | None, list[str]]:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in LOCALHOSTS:
        return None, ["--base-url must be an http(s) URL served by localhost"]
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        return None, ["--base-url must not contain credentials, a query, or a fragment"]
    return base_url.rstrip("/") + "/", []


def check_http_routes(base_url: str, routes: list[str]) -> list[str]:
    errors: list[str] = []
    base = urlparse(base_url)
    base_path = base.path.rstrip("/") + "/"
    opener = build_opener(NoRedirect())
    for route in routes:
        current = urljoin(base_url, route.lstrip("/"))
        for _ in range(6):
            try:
                response = opener.open(Request(current, method="GET"), timeout=5)
                status = response.status
                response.close()
            except HTTPError as exc:
                status = exc.code
                location = exc.headers.get("Location")
                exc.close()
                if 300 <= status < 400 and location:
                    destination = urljoin(current, location)
                    parsed = urlparse(destination)
                    if (
                        parsed.scheme != base.scheme
                        or parsed.netloc != base.netloc
                        or not parsed.path.startswith(base_path)
                    ):
                        errors.append(f"{route} redirects outside localhost base: {destination}")
                        break
                    current = destination
                    continue
                errors.append(f"{route} returned HTTP {status}")
                break
            except URLError as exc:
                errors.append(f"{route} could not be reached: {exc.reason}")
                break
            if 200 <= status < 300:
                break
            errors.append(f"{route} returned HTTP {status}")
            break
        else:
            errors.append(f"{route} exceeded redirect limit")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--routes", type=Path, help="candidate routes JSON file")
    source.add_argument("--fixture", type=Path, help="fixture directory containing routes.json")
    parser.add_argument("--base-url", help="optional localhost URL to probe")
    args = parser.parse_args()

    candidate_path = args.routes or (args.fixture / "routes.json" if args.fixture else DEFAULT_MANIFEST)
    expected, errors = load_routes(args.manifest, "manifest")
    candidate, candidate_errors = load_routes(candidate_path, "candidate")
    errors.extend(candidate_errors)
    if expected is not None and candidate is not None:
        errors.extend(compare_routes(expected, candidate))
    if args.base_url:
        base_url, base_errors = validate_base_url(args.base_url)
        errors.extend(base_errors)
        if base_url is not None and candidate is not None:
            errors.extend(check_http_routes(base_url, candidate))
    if errors:
        print("Route validation failed:", file=sys.stderr)
        print("\n".join(f"- {error}" for error in errors), file=sys.stderr)
        return 1
    print(f"Route validation passed: {len(candidate or [])} routes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
