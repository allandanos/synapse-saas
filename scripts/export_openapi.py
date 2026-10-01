"""Export (or verify) the frozen REST contract: contracts/openapi-v1.json.

The console, the four SDKs, and any language port code against this document.
CI runs `--check`; a route change without a contract update fails the build,
so contract drift is a reviewed decision rather than an accident.

    uv run python scripts/export_openapi.py          # regenerate
    uv run python scripts/export_openapi.py --check  # CI: exit 1 on drift
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT = REPO_ROOT / "contracts" / "openapi-v1.json"


def render() -> str:
    # The schema is a pure function of the routers; no DB/Redis is touched.
    os.environ.setdefault("SYNAPSE_REDIS_URL", "")
    os.environ.setdefault("SYNAPSE_AUTO_SYNC_PLANS", "false")
    # info.title/description come from branding: pin the packaged default so a
    # local .env pointing at another kit can never drift the frozen contract.
    from synapse_saas.core.config import DEFAULT_BRANDING_FILE

    os.environ["SYNAPSE_BRANDING_FILE"] = str(DEFAULT_BRANDING_FILE)
    from synapse_saas.api.app import create_app

    schema = create_app().openapi()
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main(argv: list[str]) -> int:
    rendered = render()
    if "--check" in argv:
        if not CONTRACT.exists():
            print(f"missing {CONTRACT.relative_to(REPO_ROOT)}; run without --check", file=sys.stderr)
            return 1
        if CONTRACT.read_text() != rendered:
            print(
                f"{CONTRACT.relative_to(REPO_ROOT)} is out of date with the routers.\n"
                "Regenerate with: uv run python scripts/export_openapi.py\n"
                "and describe the contract change in contracts/CHANGELOG.md.",
                file=sys.stderr,
            )
            return 1
        print("contract up to date")
        return 0
    CONTRACT.write_text(rendered)
    print(f"wrote {CONTRACT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
