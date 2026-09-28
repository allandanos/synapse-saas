"""Export the non-OpenAPI halves of the contract (P6 / WS-K, ADR 0012):

- contracts/events.json  — the webhook event vocabulary (public vs internal)
- contracts/problems.json — the RFC 7807 problem registry (title ⇒ status)

Ports and SDKs code against these alongside contracts/openapi-v1.json.
CI runs `--check`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EVENTS = REPO_ROOT / "contracts" / "events.json"
PROBLEMS = REPO_ROOT / "contracts" / "problems.json"


def render_events() -> str:
    from synapse_saas.core import events

    names = {
        name: value
        for name, value in vars(events).items()
        if name.isupper() and isinstance(value, str) and "." in value and not name.startswith("AUDIENCE")
    }
    public = sorted(v for v in names.values() if v not in events.INTERNAL_EVENTS)
    internal = sorted(events.INTERNAL_EVENTS)
    return json.dumps({"public": public, "internal": internal}, indent=2) + "\n"


def render_problems() -> str:
    import inspect

    from synapse_saas.core import errors

    # Keyed by problem `title` (what clients see); several exception classes may
    # share one title, so every class is listed and their statuses must agree.
    registry: dict[str, dict[str, object]] = {}
    for name, cls in inspect.getmembers(errors, inspect.isclass):
        if issubclass(cls, errors.DomainError) and cls is not errors.DomainError:
            entry = registry.setdefault(cls.title, {"status": cls.status, "classes": []})
            if entry["status"] != cls.status:
                raise SystemExit(
                    f"problem {cls.title!r}: {name} has status {cls.status}, registry says {entry['status']}"
                )
            classes = entry["classes"]
            assert isinstance(classes, list)
            classes.append(name)
    for entry in registry.values():
        classes = entry["classes"]
        assert isinstance(classes, list)
        classes.sort()
    return json.dumps(dict(sorted(registry.items())), indent=2) + "\n"


def main(argv: list[str]) -> int:
    rendered = {EVENTS: render_events(), PROBLEMS: render_problems()}
    if "--check" in argv:
        stale = [p for p, text in rendered.items() if not p.exists() or p.read_text() != text]
        for p in stale:
            print(
                f"{p.relative_to(REPO_ROOT)} is out of date; run scripts/export_contracts.py", file=sys.stderr
            )
        if stale:
            return 1
        print("event + problem contracts up to date")
        return 0
    for p, text in rendered.items():
        p.write_text(text)
        print(f"wrote {p.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
