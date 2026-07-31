# tai-docs

[![docs](https://github.com/tai42ai/tai-docs/actions/workflows/docs.yml/badge.svg)](https://github.com/tai42ai/tai-docs/actions/workflows/docs.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

The unified documentation site for the TAI ecosystem, built with
[Mintlify](https://mintlify.com). One site covers the whole platform: a
landing page, hand-written concepts and guides, and a generated reference
(HTTP API, CLI, Python SDK, Studio SDK, settings, and the ecosystem catalog).

The site is docs-as-code: every page is MDX in this repository, and the
reference sections are generated from source so they cannot drift from the code.

## Layout

```
docs.json              Mintlify configuration: theme, navigation, metadata
index.mdx              Landing page
getting-started/       Install, quickstart, mental model
concepts/              One page per platform pillar
guides/                Task-shaped how-to guides
integrations/          Connecting MCP clients to a running server
reference/             Generated reference (API, CLI, Python SDK, Studio SDK,
                       settings, catalog)
contributing.mdx       How the tai42 monorepo is laid out and developed
logo/                  Brand assets: favicon (icon.png) and light/dark logos
images/                Static images, including the social/OG image
STYLE.md               Voice, tense, and vocabulary guide for authors
```

## Preview locally

Install the Mintlify CLI and run the dev server from the repository root:

```bash
npm i -g mint
mint dev
```

`mint dev` renders the site at `http://localhost:3000` and hot-reloads on
change. Validate a change by confirming the navigation renders every section
with no broken internal links, in both the light and dark themes.

## Configuration

`docs.json` is the single source of navigation and site configuration. The
navigation is a set of tabs (Docs / Studio / Integrations / Reference); every
page it references exists as an `.mdx` file at the matching path.

Three delivery features are configured here and served by Mintlify's hosting
layer — there is no local build step for any of them:

- **llms.txt / llms-full.txt** — Mintlify serves these automatically for the
  hosted site.
- **Copy-as-markdown and "open in ChatGPT / Claude"** — enabled through the
  `contextual` options in `docs.json`.
- **The docs MCP server** — served at `/mcp` for the hosted site.

They are confirmed on the deploy preview, not in `mint dev`.

## Generated reference

The reference sections are generated from source so they cannot drift from the
code. The generators live in `scripts/` and run in the tai42 monorepo's
environment, where `tai42_contract`, `tai42_kit`, and `tai42_skeleton` resolve.
Regenerate all seven from a monorepo checkout beside this one:

```bash
cd ../tai42/core/skeleton
uv run python ../../../tai-docs/scripts/gen_openapi.py    # openapi.json (HTTP API)
uv run python ../../../tai-docs/scripts/gen_cli.py        # reference/cli/*.mdx
uv run python ../../../tai-docs/scripts/gen_sdk.py        # reference/python-sdk/*.mdx
uv run python ../../../tai-docs/scripts/gen_studio_sdk.py # reference/studio-sdk/*.mdx
uv run python ../../../tai-docs/scripts/gen_catalog.py    # reference/catalog/index.mdx
uv run python ../../../tai-docs/scripts/generate-settings-reference.py  # reference/settings.mdx
uv run python ../../../tai-docs/scripts/gen_toolbox_table.py  # guides/standard-toolbox.mdx table
```

Each generator fails loud: if its input cannot be loaded it exits non-zero and
leaves the committed reference untouched, never overwriting a good reference
with an empty or partial one. The `openapi` field in `docs.json` points at the
emitted `openapi.json`; the CLI, Python-SDK, Studio-SDK, catalog, and settings
generators also rewrite their own Reference nav entries in `docs.json`. `gen_toolbox_table.py` rewrites only the
generated table between the markers in `guides/standard-toolbox.mdx`, sourced
from the same packaged `ecosystem.yml` as the catalog.

## Freshness checks

Three checks keep the committed reference honest. Run the first two from a
monorepo checkout (they need the source packages); the third is offline:

```bash
cd ../tai42/core/skeleton
uv run python ../../../tai-docs/scripts/check_drift.py      # committed reference == fresh regen
uv run python ../../../tai-docs/scripts/check_registry.py   # catalog packages resolve to repos

cd ../../../tai-docs
python3 scripts/check_docs.py                         # static build validation
```

- **`check_drift.py`** re-runs every generator and fails if the committed
  reference differs from a fresh run — the "generated files are checked in AND
  verified fresh in CI" pattern. It is non-mutating (it snapshots, regenerates,
  diffs, and restores).
- **`check_registry.py`** asserts every catalog entry's `package` resolves
  through `ecosystem.yml`'s package→repo mapping and that each repo is a real
  checkout. The deeper pip-install-each-plugin boot cross-check is a hosted-CI
  step (see below).
- **`check_docs.py`** is the offline build gate: `docs.json` parses, every nav
  page resolves to a file, every redirect destination exists, and every
  internal link resolves. It stands in for `mint` here — since the Mintlify CLI
  is not available offline, this static validation is the local build gate.

The generator unit tests run the same way:

```bash
python3 scripts/test_generators.py                    # offline (no skeleton env)
cd ../tai42/core/skeleton
uv run python ../../../tai-docs/scripts/test_gen_sdk.py
uv run python ../../../tai-docs/scripts/test_gen_catalog.py
```

The Python under `scripts/` is linted with `ruff` (config in `pyproject.toml`,
aligned with the monorepo): `ruff check scripts/` and
`ruff format --check scripts/`.

## CI freshness pipeline

`.github/workflows/docs.yml` runs the freshness pipeline in hosted CI (it needs
the source checkouts, `uv`, and `mint`, so it does not run in an offline
checkout). On pull requests and pushes it runs the drift gate, registry
cross-check, examples type-check (`uv run pyright ../../../tai-docs/examples/` from the
synced `tai42-skeleton` env, so the examples resolve the real
`tai42_contract`/`tai42_kit`/`starlette`/`makefun`/`pydantic` deps, plus
`scripts/sync_examples.py --check`, both required — an absent `examples/` makes
pyright error and a present-but-empty `examples/` trips `sync_examples.py`'s
zero-file guard, so the gate never skips clean), and a Mintlify build + link
check. On the source-repo push hook, manual dispatch, and a daily schedule it
regenerates the reference against source `main` HEAD and opens an
automated PR when the output drifts — it never pushes to `main`, so the deployed
site always builds from committed files. `ci/source-repo-docs-hook.yml` is the
template each source repo (the tai42 monorepo and tai-studio) copies into its
workflows to fire that hook.

The tai42 monorepo and tai-studio each ship the `notify-docs` workflow, so a
push to `main` in either fires the `regenerate` job. Two
further triggers act as safety nets — the `docs` workflow's `workflow_dispatch`
(Actions tab "Run workflow", or `gh workflow run docs.yml`) and a daily
`schedule` (cron `17 6 * * *`, ~06:17 UTC). Every path regenerates against
source `main` HEAD and opens the automated regeneration PR if anything
drifted; nothing is pushed to `main` directly.

Permissions are scoped per job: `gate` is `contents: read` (it only validates),
`regenerate` is `contents: write` + `pull-requests: write` (it opens the PR).

Two hosted-CI secrets are required:

- **`TAI_DOCS_DISPATCH_TOKEN`** — set in each source repo, the tai42 monorepo
  and tai-studio (see
  `ci/source-repo-docs-hook.yml`); a token with `contents: write` on tai-docs,
  used to fire the cross-repo regeneration dispatch.
- **`TAI_DOCS_PR_TOKEN`** — set in tai-docs; a PAT/App token with `contents: write`
  + `pull-requests: write`, passed to `create-pull-request` so the automated
  regeneration PR triggers the `gate` job. (A PR opened with the default
  `GITHUB_TOKEN` does not trigger further workflows, so the drift gate would
  never run on the bot PR.)

## Brand assets

`logo/` holds the TAI42 brand art: `icon.png` is the favicon, `light.png` and
`dark.png` are the header logos (329×130), and `images/og-image.svg` is the
social card. The `colors` block in `docs.json` carries the crimson accent.

## License

Apache-2.0. See `LICENSE` and `NOTICE`.
