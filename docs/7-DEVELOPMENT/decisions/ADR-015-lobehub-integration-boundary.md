# ADR-015: LobeHub integration boundary

- Status: accepted for this iteration; commercial licensing requires review
- Date: 2026-10-13

## Context

The user requested that MCIT AI use LobeHub's agent UI and potentially replace its agent or
entire application core. LobeHub was inspected from a shallow clone in a temporary directory.
Its root `LICENSE` is the LobeHub Community License, not the MIT license governing Open
Notebook. It requires a commercial license to develop and distribute a commercial derivative.
Its agent runtime is a private TypeScript workspace package tied to different host services.
The full application uses PostgreSQL/Drizzle, Redis, S3-compatible object storage and different
authentication and storage semantics from MCIT AI's FastAPI/SurrealDB/SQLite/local volumes.

## Decision

Do not copy LobeHub application source into this fork or silently replace the backend. Continue
using the already-installed published `@lobehub/ui` components, subject to their own package
license review. Implement Agent UI interaction patterns within MCIT AI's existing API while
preserving notebooks, Studio, Ollama and Kokoro. Bundle only the user-specified MCIT avatar
images locally so normal application use never fetches avatars from GitHub.

## Consequences

- Whole-core migration remains a separate architectural and licensing decision requiring
  rights, data migration, an authentication design, an egress audit, deployment changes and
  dedicated end-to-end tests. This iteration does not claim LobeHub runtime parity.
- MCIT AI still stores chat history in browser localStorage and artifacts on local volumes; see
  `PRIVACY_AUDIT.md`. None of these facts supports a claim of 100% data sovereignty yet.
