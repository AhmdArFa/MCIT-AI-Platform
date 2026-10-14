# MCIT AI

The private AI workspace of the Ministry of Communications and Information Technology:
notebooks over your sources, a notebook chat, Studio for finished documents, and
**Tut Agent** for multi-step work. One sign-in covers everything, and every account is
private to its owner.

Developed by Eng Ahmed Arfa for MCIT.

## What is in the platform

| Part | What it does |
|---|---|
| **Tut Agent** | The single agent of MCIT AI: the MCIT-Agent app ([`agent/`](agent), submodule) with its agent runtime, tools, skills, knowledge bases, memory, multi-agent groups and its own interface. Embedded in MCIT AI at `/tut`. It reaches MCIT AI notebooks and Studio through the MCIT AI MCP server; Studio runs the Craft engines behind its API. |
| **Notebooks** | Sources (files, links, text), notes, search and a **chat**: Tut answers from the context you select, with citations. The chat only converses; it runs no tools and no automation. |
| **Studio** | Four presets: **Presentation** (dark or light), **Report** (dark or light), **Sketchnote infographic** and **Noir spreadsheet**. Tut Agent writes the content from the notebook; the Craft engines build the files. |
| **Craft engines** | The real ArtCraft CLIs run headlessly inside the backend and are never shown to users: GridCraft (spreadsheets), DeckCraft (PowerPoint), WordCraft (Word), PdfCraft (PDF), VectorCraft (designs and infographics) and EffectCraft (motion). Presentations are constructed with PptxGenJS and finished by DeckCraft. Sources in [`craft/vendor/`](craft/vendor) (submodules, pinned to the release tags the image installs). |
| **Office viewer** | ONLYOFFICE Docs opens every office file (docx, xlsx, pptx, pdf) and can edit it. Saves go back to the same file in the library, so Craft outputs and edits stay in sync. |
| **Accounts** | Administrators create accounts and set passwords; members use the workspace. Each account has its own database and files. |

### Studio pipelines

| Preset | Pipeline | Files |
|---|---|---|
| Presentation | Tut writes the deck → PptxGenJS builds slides in the Midnight Noir or light theme → DeckCraft validates the deck and exports the PDF copy | `.pptx`, `.pdf` |
| Report | Tut writes the report → styled HTML → WordCraft builds the Word file (page colour for dark) and exports the PDF → PdfCraft sets properties and verifies pages | `.docx`, `.pdf` |
| Sketchnote infographic | Tut writes the one-pager → hand-drawn style SVG → VectorCraft exports PDF and PNG | `.svg`, `.pdf`, `.png` |
| Noir spreadsheet | Tut extracts the tables → GridCraft builds the workbook and applies the Noir styling | `.xlsx` |

Studio uses the signed-in user's MCIT-Agent Responses API key, not a separate imitation
of the agent. In **Account → Studio connection**, enter a personal Tut Agent API key
with `model:invoke`, `chat:write` and `agent:write` scopes. The key is encrypted in
that user's private database. Studio fails clearly if Tut Agent is not connected.

Code: [`open_notebook/craft/`](open_notebook/craft) (engine registry, MCP stdio client, pipelines),
[`api/routers/studio.py`](api/routers/studio.py), [`api/routers/office.py`](api/routers/office.py).

## Accounts and privacy

- **Bootstrap administrator**: `admin` / `1234`, created on first start
  (`MCIT_ADMIN_USERNAME`, `MCIT_ADMIN_PASSWORD`). Change the password from **Account** or the
  admin console before sharing the instance.
- **Administrators**: full permissions; the **Admin console** (`/admin`) has account management
  (create, reset password, change role, disable, delete), monitoring (services, Craft engines,
  background jobs, token totals, activity log) and a panel per user with their chats,
  generations, usage and activity.
- **Members**: a reduced, use-only interface: Tut Agent, notebooks, sources, search, files,
  podcasts, their own usage and account. Platform configuration (models, credentials,
  transformations, settings) is administrator-only; the API enforces this, not only the UI.
- **Isolation**: every account has a private SurrealDB database (`u_<account id>`), a private data
  folder (`data/users/u_<account id>`) and namespaced chat history. The server binds each request
  to the signed-in account; a client cannot choose another account's storage. Only
  administrators can open another account's data, through the admin console.
- **One login**: MCIT AI is the OpenID Connect provider for Tut Agent
  (`/api/oidc`). Tut Agent has password sign-in disabled and signs users in through MCIT AI.

Implementation: [`open_notebook/tenancy.py`](open_notebook/tenancy.py),
[`open_notebook/accounts.py`](open_notebook/accounts.py), [`api/auth.py`](api/auth.py),
[`api/routers/admin.py`](api/routers/admin.py), [`api/routers/oidc.py`](api/routers/oidc.py).
Tests: [`tests/test_auth.py`](tests/test_auth.py).

## Run

```bash
git clone --recurse-submodules https://github.com/AhmdArFa/MCIT-AI-Platform.git
cd MCIT-AI-Platform
cp .env.example .env            # replace every CHANGE_ME (openssl rand -hex 32)
docker compose up -d --build    # MCIT AI, Tut Agent, office viewer, local models and speech
```

| Address | Service |
|---|---|
| http://localhost:8502 | MCIT AI (sign in as `admin` / `1234`) |
| http://localhost:3210 | Tut Agent (signs in through MCIT AI) |
| http://localhost:8082 | Office viewer (loaded by MCIT AI; no direct use) |

The first start downloads the `qwen2.5:7b` and `nomic-embed-text` models. The MCIT AI image
downloads the Craft engine releases at build time.

### Connect Tut Agent to MCIT AI tools

In MCIT AI open **Account → Connect Tut Agent to MCIT AI** and create a token. In Tut Agent add an
MCP server with the shown URL (`/api/mcp`) and `Authorization` header. Tut then has tools to list
and read notebooks, search sources, save notes, and run Studio presets. Direct arbitrary Craft
MCP calls are withheld until every engine can run in an OS-level per-user filesystem sandbox;
the Studio pipelines use server-controlled Craft invocations instead.

## Develop

```bash
uv sync                                   # backend
uv run pytest tests/                      # backend tests
cd frontend && npm ci && npm test         # frontend tests
npm run lint && npx tsc --noEmit
```

Craft engines for local development: download the `*-cli` binaries from the releases pinned in the
[`Dockerfile`](Dockerfile) and set `CRAFT_BIN_DIR`. The deck builder needs
`npm ci` in [`open_notebook/craft/deck`](open_notebook/craft/deck).

More: [AGENTS.md](AGENTS.md), [docs/7-DEVELOPMENT/](docs/7-DEVELOPMENT/index.md),
[ADR-016](docs/7-DEVELOPMENT/decisions/ADR-016-tut-agent-craft-engines-accounts.md).

## Before production

Read [PRIVACY_AUDIT.md](PRIVACY_AUDIT.md). Set strong secrets and a new administrator password,
put the services behind TLS, and keep SurrealDB, the office viewer and the engines off the public
network. Tut Agent is derived from LobeHub; confirm its license terms for your deployment.

## Remaining Integration Work

- The MCIT AI admin console shows its own per-user notebook chats, files, generations and
  model usage. Tut Agent stores chats and usage separately; they are not yet aggregated into
  the MCIT AI admin console. Do not treat its totals as platform-wide totals.
- The pinned MCIT-Agent frontend still has a few upstream onboarding/sign-in strings and
  third-party references. Those require a branded MCIT-Agent source revision; the platform
  proxy only hides the legacy browser Studio editors, without changing agent capabilities.
- Tut's OIDC login is shared with MCIT AI, but its browser session is separate. Signing out
  of MCIT AI does not terminate an already active Tut session. An SSO single-logout flow is
  required before claiming session-level single sign-out.
- Studio's Tut Responses API connection is tested with mocked responses and user-scoped
  keys; a full model run through Tut with Ollama and a real key has not yet been verified.
- Free-form Craft MCP commands are unavailable to users until GridCraft, DeckCraft and
  EffectCraft have OS-enforced per-account filesystem isolation. The fixed Studio pipelines
  run all their document work through the real Craft binaries.
