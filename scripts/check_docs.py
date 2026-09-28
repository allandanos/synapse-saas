"""Keep the hand-written docs honest against the code (P4 / WS-G).

Two checks, both run in CI (`--check`) and locally (`--fix` rewrites what it can):

1. docs/api.md must mention every operation in contracts/openapi-v1.json —
   a route added without a doc row fails the build. The table stays
   hand-written (it carries permissions and semantics no generator knows);
   this only proves nothing is missing.
2. docs/webhooks.md carries a generated event catalog between
   `<!-- events:start -->` / `<!-- events:end -->`, rendered from
   core/events.py (public vs internal). `--fix` rewrites it; `--check` diffs.

    uv run python scripts/check_docs.py --fix
    uv run python scripts/check_docs.py --check
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT = REPO_ROOT / "contracts" / "openapi-v1.json"
API_DOC = REPO_ROOT / "docs" / "api.md"
WEBHOOKS_DOC = REPO_ROOT / "docs" / "webhooks.md"
START, END = "<!-- events:start -->", "<!-- events:end -->"

# Documented elsewhere on purpose (operational endpoints, not the tenant API)
API_DOC_EXEMPT = {("get", "/metrics")}


def _norm(path: str) -> str:
    path = re.sub(r"\{[^}]+\}", "{}", path)
    return path.removeprefix("/v1") or "/"


def contract_operations() -> set[tuple[str, str]]:
    schema = json.loads(CONTRACT.read_text())
    ops = set()
    for path, methods in schema["paths"].items():
        for method in methods:
            ops.add((method.lower(), _norm(path)))
    return ops


def documented_operations() -> set[tuple[str, str]]:
    """(method, path) pairs from every table row: `| GET/POST | \\`/a\\`, \\`/b\\` | …`."""
    ops: set[tuple[str, str]] = set()
    for line in API_DOC.read_text().splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        methods = [m.strip().lower() for m in re.split(r"[/,]", cells[0]) if m.strip()]
        paths = re.findall(r"`([^`]+)`", cells[1])
        for method in methods:
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            for raw in paths:
                path = raw.split("?")[0].strip()
                if path.startswith("/"):
                    ops.add((method, _norm(path)))
    return ops


def render_event_catalog() -> str:
    from synapse_saas.core import events

    names = {
        name: value
        for name, value in vars(events).items()
        if name.isupper() and isinstance(value, str) and "." in value and not name.startswith("AUDIENCE")
    }
    public = sorted(v for v in names.values() if v not in events.INTERNAL_EVENTS)
    internal = sorted(events.INTERNAL_EVENTS)
    lines = [
        START,
        "",
        "_Generated from `core/events.py` by `scripts/check_docs.py --fix`; do not edit by hand._",
        "",
        "**Public** — fan out to tenant webhook endpoints (subject to each endpoint's `events` filter):",
        "",
        *(f"- `{e}`" for e in public),
        "",
        "**Internal** — consumed in-process only (email handlers); never delivered to a webhook:",
        "",
        *(f"- `{e}`" for e in internal),
        "",
        END,
    ]
    return "\n".join(lines)


def check_api_doc() -> list[str]:
    missing = sorted(contract_operations() - documented_operations() - API_DOC_EXEMPT)
    return [f"docs/api.md lacks a row for {m.upper()} {p}" for m, p in missing]


def check_or_fix_events(fix: bool) -> list[str]:
    text = WEBHOOKS_DOC.read_text()
    block = render_event_catalog()
    if START not in text or END not in text:
        if not fix:
            return ["docs/webhooks.md has no event-catalog markers; run --fix"]
        text = text.rstrip("\n") + "\n\n" + block + "\n"
        WEBHOOKS_DOC.write_text(text)
        return []
    start, end = text.index(START), text.index(END) + len(END)
    current = text[start:end]
    if current == block:
        return []
    if fix:
        WEBHOOKS_DOC.write_text(text[:start] + block + text[end:])
        return []
    return ["docs/webhooks.md event catalog is out of date; run scripts/check_docs.py --fix"]


def main(argv: list[str]) -> int:
    fix = "--fix" in argv
    problems = check_api_doc() + check_or_fix_events(fix)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    print("docs in sync with the contract and the event vocabulary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
