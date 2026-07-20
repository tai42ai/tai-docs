#!/usr/bin/env python3
"""Registry cross-check: the ecosystem catalog's offline freshness guarantee.

The catalog page is generated from the STATIC ``ecosystem.yml`` shipped inside
the ``tai_skeleton`` package. This check asserts the file's own integrity so the
"generated from the registries" claim holds offline: every catalog entry names
a ``package`` that resolves through the file's ``package -> repo`` mapping, and
every repo in that mapping resolves to an actual sibling repository checkout.

This is the offline half of the freshness guarantee. The deeper boot-check --
pip-install each package from its repo's ``main``, boot an ephemeral in-process
skeleton, and assert each declared registration actually appears in the live
``tai_app`` -- requires network installs and is a hosted-CI step (see
``.github/workflows/docs.yml``); it cannot run in this offline environment.

Run it where ``tai_skeleton`` resolves (the tai-skeleton virtualenv)::

    cd tai-skeleton && uv run python ../tai-docs/scripts/check_registry.py
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DOCS_ROOT = SCRIPT_DIR.parent
WORKSPACE_ROOT = DOCS_ROOT.parent
sys.path.insert(0, str(SCRIPT_DIR))

import gen_catalog  # noqa: E402

# Every field a catalog entry must carry; the same contract gen_catalog renders.
_ENTRY_FIELDS = ("name", "kind", "group", "package", "module", "description")


def main() -> int:
    doc = gen_catalog.load_ecosystem()
    entries = doc.get("entries")
    packages = doc.get("packages")

    problems: list[str] = []

    if not entries:
        problems.append("ecosystem.yml has no entries")
    if not isinstance(packages, dict) or not packages:
        problems.append("ecosystem.yml has no packages mapping")
    if problems:
        for p in problems:
            print(f"check_registry: {p}", file=sys.stderr)
        return 1

    # (a) every entry is complete and its package resolves through the mapping.
    for i, entry in enumerate(entries):
        missing = [f for f in _ENTRY_FIELDS if f not in entry]
        if missing:
            problems.append(f"entry #{i} ({entry.get('name', '?')}) missing fields: {', '.join(missing)}")
            continue
        pkg = entry["package"]
        if pkg not in packages:
            problems.append(f"entry '{entry['name']}' names package '{pkg}', absent from the package -> repo mapping")

    # (b) every repo the mapping points at resolves to a sibling checkout.
    for pkg, repo in packages.items():
        if not isinstance(repo, str) or not repo.strip():
            problems.append(f"package '{pkg}' maps to an empty repo")
            continue
        if not (WORKSPACE_ROOT / repo).is_dir():
            problems.append(
                f"package '{pkg}' maps to repo '{repo}', which is not a sibling checkout of this repository"
            )

    if problems:
        print("check_registry: MISMATCH between ecosystem.yml and the repos:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    print(
        f"check_registry: OK -- {len(entries)} entries, "
        f"{len(packages)} packages, every package resolves to a repo checkout."
    )
    print("  (offline mapping-integrity check; the pip-install + in-process boot cross-check runs in hosted CI.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
