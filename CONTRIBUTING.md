# Contributing to tai-docs

`tai-docs` is the source of the TAI documentation site at
[tai42.ai](https://tai42.ai). Pages are MDX in this repo and the navigation lives
in `docs.json`. The site is deployed from committed files on `main`, so a merged
change is a published change — this repo ships no released version of its own.
The shared contribution discipline for the whole ecosystem — including where each
repository's own guide lives — is documented on the site itself, which is the
single source of truth:

**https://tai42.ai/contributing**

Please read that page before opening a documentation pull request.

## Ground rules

- **Follow the style guide.** [STYLE.md](STYLE.md) fixes the voice, tense, and
  vocabulary every page on the site follows; it is a mandatory input to any
  narrative page.
- **Never hand-edit generated reference.** `reference/cli/`,
  `reference/python-sdk/`, `reference/studio-sdk/`, `reference/catalog/`,
  `reference/settings.mdx`, `openapi.json`, and the standard-toolbox table in
  `guides/standard-toolbox.mdx` are written by the generators in `scripts/`.
  Change the source repository or the generator and regenerate;
  `scripts/check_drift.py` fails the build when a committed page differs from a
  fresh regeneration.
- **Examples are single-sourced and executed.** Every worked example lives once
  under `examples/`. `scripts/sync_examples.py` renders it into
  `snippets/examples/` for the guides to import, and `scripts/run_examples.py`
  runs the `.sh` / `.yaml` ones against a live app, asserting the outcome each
  declares in its `#|` metadata block. Edit the file under `examples/`, never
  the generated snippet.
- **The site must still build.** `scripts/check_docs.py` is the offline stand-in
  for the hosted Mintlify build: it validates that `docs.json` parses, that
  every navigation entry and redirect resolves to a real page, and that every
  internal link points at an existing page or asset.

## Layout

Narrative content:

- `index.mdx` — the site landing page; `contributing.mdx` — the site's own
  contributing page
- `getting-started` — installation, quickstart, and the mental model
- `concepts` — what each part of the platform is
- `guides` — task-shaped how-tos, with `guides/authors` covering the author path
  for every plugin type
- `studio` — the Studio UI: screens, login, API keys, plugins, deploy
- `integrations` — connecting MCP clients (Claude Desktop, Cursor, and others)
- `marketplace` — browsing, installing, and advisories

Generated reference:

- `reference/cli`, `reference/python-sdk`, `reference/studio-sdk`,
  `reference/catalog`, `reference/settings.mdx` — generated from the source
  repositories
- `reference/api` — the HTTP API section, rendered from the generated
  `openapi.json`
- `snippets/examples` — generated MDX wrappers of the `examples` tree, imported
  by the guides

Tooling and assets:

- `examples` — the single source of every worked example
- `scripts` — the reference generators, the freshness/integrity checks, and
  their own pytest suite
- `ci` — `source-repo-docs-hook.yml`, the workflow template each source repo
  copies in to trigger a reference rebuild
- `docs.json` — the Mintlify configuration: navigation, theme, and redirects
- `images`, `logo` — static assets

## Dev

Preview the changed pages locally with the Mintlify CLI:

```bash
npm i -g mint                # the Mintlify CLI
mint dev                     # local preview of the changed pages
```

The `scripts/` directory carries the site's helper tooling and its own tests; if
you change it, keep it green:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

For local cross-repo work, `make dev` editable-installs the sibling `tai-*`
checkouts this package builds on into the venv. While `[tool.uv.sources]` pins
those siblings to local paths, `uv sync` already installs them editable and
`make dev` changes nothing; once the lock resolves them from the registry,
`uv sync` / `uv run` installs the published builds instead, so re-run
`make dev` afterward to restore the editable links.

Before any commit, run a secret scan over `scripts/` and `examples/` (e.g.
`detect-secrets scan`).

For security reports see [SECURITY.md](SECURITY.md); for community expectations
see [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

By contributing you agree your contributions are licensed under Apache-2.0.
