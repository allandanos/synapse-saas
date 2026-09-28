"""Every operation in the frozen contract has a method in every SDK (P6 / WS-K).

Static, not runtime: an operation counts as covered when an SDK source file
mentions the route's literal path segments (parameters wildcarded) together with
the HTTP method on the same statement. Routes that are browser redirects or
provider-to-server calls are exempt — no client SDK should expose them.

    uv run python scripts/sdk_coverage.py          # report
    uv run python scripts/sdk_coverage.py --check  # non-zero exit on any gap
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "openapi-v1.json"

SDK_SOURCES = {
    "python": [ROOT / "sdk/python/synapse_saas_client/client.py"],
    "typescript": [ROOT / "sdk/typescript/src/client.ts"],
    "go": [ROOT / "sdk/go/client.go", ROOT / "sdk/go/resources.go"],
    "java": [ROOT / "sdk/java/src/main/java/dev/synapse/client/SynapseClient.java"],
}

# Not SDK surface: browser redirects, provider webhooks, probes, scraping.
EXEMPT = {
    ("GET", "/v1/auth/oidc/start"),
    ("GET", "/v1/auth/oidc/callback"),
    ("POST", "/v1/billing/webhooks/{provider}"),
    ("GET", "/healthz"),
    ("GET", "/readyz"),
    ("GET", "/metrics"),
}


def operations() -> list[tuple[str, str]]:
    spec = json.loads(CONTRACT.read_text())
    return sorted(
        (method.upper(), path)
        for path, ops in spec["paths"].items()
        for method in ops
        if (method.upper(), path) not in EXEMPT
    )


# How each SDK spells a path parameter, normalised to `{}` before matching.
_PARAM_FORMS = (
    re.compile(r"\$\{[A-Za-z_][\w.()]*\}"),  # TS template literal `${agentId}`
    re.compile(r"\{[A-Za-z_][\w.]*\}"),  # Python f-string {role_id} (identifier only: never a code block)
    re.compile(r'"\s*\+\s*[\w.()]+\s*\+\s*"'),  # Go/Java: "…/" + id + "/…"
    re.compile(r'"\s*\+\s*[\w.()]+(?=\s*[,)}\n])'),  # Go/Java trailing: "…/" + id
)
_QUOTES = "\"'`"
_GET_HELPERS = re.compile(r"\b(page|callPage|_page|bytes|callBytes|_bytes)\(")
_WINDOW = 260  # chars before the path where the method literal must appear


def _normalise(source: str) -> str:
    out = source
    out = _PARAM_FORMS[0].sub("{}", out)
    out = _PARAM_FORMS[1].sub("{}", out)
    out = _PARAM_FORMS[2].sub("{}", out)
    out = _PARAM_FORMS[3].sub('{}"', out)
    return out


def covered(source: str, method: str, path: str) -> bool:
    canonical = re.sub(r"\{[^}]+\}", "{}", path)
    normalised = _normalise(source)
    for quote in _QUOTES:
        needle = f"{quote}{canonical}{quote}"
        start = 0
        while (at := normalised.find(needle, start)) != -1:
            window = normalised[max(0, at - _WINDOW) : at]
            if f'"{method}"' in window or (method == "GET" and _GET_HELPERS.search(window)):
                return True
            start = at + 1
    return False


def report() -> dict[str, list[tuple[str, str]]]:
    ops = operations()
    gaps: dict[str, list[tuple[str, str]]] = {}
    for sdk, files in SDK_SOURCES.items():
        source = "\n".join(f.read_text() for f in files)
        gaps[sdk] = [(m, p) for m, p in ops if not covered(source, m, p)]
    return gaps


def main(argv: list[str]) -> int:
    check = "--check" in argv
    ops = operations()
    gaps = report()
    for sdk, missing in gaps.items():
        print(f"{sdk:11s} {len(ops) - len(missing):3d}/{len(ops)} operations")
        for method, path in missing:
            print(f"    missing {method:6s} {path}")
    failed = any(gaps.values())
    if check and failed:
        print("\nsdk_coverage: every SDK must cover every non-exempt contract operation", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
