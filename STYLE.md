# Style guide

The voice, tense, and vocabulary every page on this site follows. It is a
mandatory input to anyone authoring narrative content.

## Voice

- Direct and concrete. Address the reader as "you"; refer to the platform as
  "tai" or "the runtime", never "we".
- Explain what a thing **is** and what it **does** — never how it came to be.
  No history, no roadmap, no "coming soon", no references to plans, missions,
  streams, or pull requests.
- Lead with the point. The first sentence of a page states what the page is
  for; the first sentence of a section states its takeaway.

## Tense and mood

- Present tense for behaviour that is always true: "The manifest names the
  tools a server loads."
- Imperative mood for steps the reader performs: "Add the module to the
  manifest, then restart the server."
- Active voice. Name the actor: "the connector engine loads its catalog", not
  "the catalog is loaded".

## Structure

- Short paragraphs — three sentences or fewer. Prefer a list or a `Steps`
  block over a long paragraph when describing a sequence.
- One idea per section. Cross-link a concept the first time it appears rather
  than re-explaining it.
- Every concept page links out to the reference page for the surface it
  describes.

## Vocabulary (use these exact terms)

- **tool** — the atom of work: a plain Python function or a mounted MCP server.
- **extension** — a clip-on power that wraps or transforms a tool into a new
  variant. Not a "plugin" and not a "middleware".
- **preset** — a versioned, named wrap of a tool.
- **agent** — an LLM-driven capability registered alongside tools.
- **connector** — an OAuth connection to an outside app.
- **manifest** — the declarative file a server loads at startup.
- **the runtime** / **a server** — a running skeleton. Say "the platform" for
  the whole system, "a server" for one running instance.
- **plugin** — any separately-shipped package that registers through the
  contract handle (connectors, storage, config, backends, monitoring,
  verifiers). Reserve the word for these; a tool or extension you write in
  your own app is not a "plugin".

Write "MCP client", "the MCP endpoint", "OAuth provider" — lowercase common
nouns, capitalised product names.

## Code samples

- Every code sample is real: copied from a passing test or an example file,
  never invented. Do not write an API call that does not exist.
- Worked examples that pages import are minimal and self-contained — never a
  shipped implementation.

## Components

- A `CardGroup` on every section index.
- `Steps` for the quickstart and any ordered procedure.
- `CodeGroup` wherever a task has more than one variant (CLI and SDK, or HTTP).
- `Note` / `Warning` / `Tip` for caveats.
- Per-page frontmatter — `title`, `description`, and an `icon` from the icon
  map — on every page.

## The impl-docs boundary

The site documents the **platform** — concepts and contracts. It does not
document a third-party plugin's specifics; those live in that plugin's own
repository README, and it appears here only as a catalog row. Plain hyperlinks
out to a repository are always fine — a link is not documentation.

The one carve-out is **operator setup for a first-party shipped
implementation**: the channel guides under Guides and the setup pages under
Operate and Integrations do carry a plugin's env vars, its manifest wiring, and
the provider-side console steps, because an operator cannot stand the platform
up without them. Those pages document setup only — behaviour, internals, and
API surface stay in the plugin's own repository.
