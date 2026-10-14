# ADR-014: MCIT LM assistant, Studio exports and skills

- Status: accepted
- Date: 2026-10-12

## Context

MCIT LM needs (1) professional document outputs (decks, reports, infographics, summaries) from notebook
material, (2) a chat assistant that can operate the whole app, and (3) reusable writing instructions,
all running on a local 7B model (qwen2.5:7b, 8k context) without cloud keys.

## Decision

- **Studio** (`open_notebook/exports/`): one LLM call returns a JSON `StudioDocument`; renderers turn the
  same structure into PDF (reportlab), DOCX (python-docx), PPTX (python-pptx), SVG, HTML, MD, TXT, JSON.
  Decks use typed slide layouts (bullets, cards, stats, native chart, two-column, comparison, process,
  quote) and six themes, following the Anthropic pptx skill guidance (no accent bars, dark/light sandwich,
  native charts, speaker notes). The parser repairs small-model drift (missing fields downgrade layouts).
  Generated files are stored under `data/studio/` with a JSON index (no DB schema change).
- **Assistant** (`open_notebook/agent/`): LangChain tool calling on the default `tools` model. Tools call
  the app's own REST API (same contract as the UI) except Studio generation, which runs in-process.
  Runs are background asyncio tasks polled by the UI (`/api/agent/runs/{id}`), so long multi-file jobs
  do not hit HTTP timeouts. Run state is in memory (single API process); conversations live in the
  browser's localStorage.
- **Skills**: built-in no-ai-slop and humanizer (MIT) are enabled by default as compact digests that fit
  the 8k window; full originals are kept in `open_notebook/agent/skills_reference/`. User skills are JSON
  under `data/agent/skills.json`. Enabled skills are injected into assistant and Studio prompts.
- **UI**: @lobehub/ui provides the chat primitives (ChatItem, ChatInputArea, Markdown), Segmented,
  SliderWithInput, Switch and FileTypeIcon; existing shadcn/Tailwind pages keep working under a neutral
  design token set.

## Consequences

- No new database tables or migrations; restarting the API drops in-flight agent runs.
- Small models occasionally pass names instead of ids; tools resolve notebook references by id, then
  name, then the current notebook.
- External plugins (MCP servers) are not wired yet; skills cover instruction packs only.
