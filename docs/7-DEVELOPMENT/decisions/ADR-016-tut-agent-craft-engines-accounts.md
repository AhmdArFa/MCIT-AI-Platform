# ADR-016: Tut Agent, Craft engines, ONLYOFFICE and per-account isolation

Status: accepted. Supersedes ADR-015 (LobeHub integration boundary) and the Studio
renderers and in-app editors of ADR-014.

## Context

MCIT AI grew three overlapping assistants (Thoth agent, notebook assistant, Studio
generator), its own document renderers and in-browser editors, and a single shared
password. MCIT now needs one professional agent, document output built by the real
ArtCraft engines, one office viewer, and accounts where each person sees only their own
work.

## Decision

1. **Tut Agent is the only agent.** The MCIT-Agent app is included as the `agent/`
   submodule and runs as its own service with all of its abilities. MCIT AI embeds it at
   `/tut` and exposes its own capabilities to it as an MCP server (`/api/mcp`). The Thoth
   runner, tools, skills store and agent pages are removed. Studio and notebook chat use
   the Tut identity and writing rules (`open_notebook/tut`).
2. **Notebook chat is conversation only.** No tools, no actions; it points the user to
   Studio or Tut Agent for work.
3. **Craft engines are headless backend engines.** The official `*-cli` binaries are
   installed in the image and called through `open_notebook/craft` by CLI for the Studio
   pipelines and over MCP stdio inside the backend. Direct arbitrary engine MCP calls
   are not exposed to Tut Agent until OS-level filesystem isolation is available;
   the upstream GridCraft, DeckCraft and EffectCraft CLIs accept absolute paths.
   The Python renderers and the embedded editors in MCIT AI are removed.
4. **ONLYOFFICE Docs is the office viewer and editor.** The backend signs configs and
   issues short-lived file/callback tickets; saves replace the library file.
5. **Studio has four presets**: presentation (dark/light), report (dark/light),
   sketchnote infographic, Noir spreadsheet.
6. **Accounts and isolation.** Accounts live in the core database; each account gets a
   private SurrealDB database selected per request from the session, and a private data
   folder. Platform configuration tables stay in the core database
   (`tenancy.SHARED_TABLES`). Background jobs carry the tenant explicitly. MCIT AI is the
   OIDC provider for Tut Agent so there is one login.

## Consequences

- Isolation does not depend on every query filtering by owner: a request can only reach
  its own database. New tables are private by default; only add a table to
  `SHARED_TABLES` when it is platform configuration.
- A query that mixes shared and private tables runs against the private database; keep
  them separate.
- The MCIT-Agent stack adds PostgreSQL, Redis, object storage, a gateway and a search
  service. All services start together through the platform Compose file.
- MCIT-Agent still ships its own browser Studio (DeckCraft/PDF Craft editors) in the
  submodule. The published Tut Agent frontend is proxied through `tut-ui`, which blocks
  those two legacy paths while retaining the agent runtime and all its other routes.
