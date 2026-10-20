# Spec: campaign creation and reference library

**Status:** issues 1–4 are implemented. The workspace skill supports open-ended
creation, maintenance and play, with conflict-safe installs and separate working
notes. The reference library provides per-source local indexing and model-excerpt
permissions, full-document passage embeddings through the local Ollama service,
semantic search and citations, and explicit approval before reindexing a changed
source. OCR handles text-empty PDF pages using local Tesseract and Poppler tools.

The [workspace contract](../contracts/workspace-layout.md#campaign-workshop-and-reference-library-spec-12-first-delivery)
documents commands, storage, permissions and operational limits. Embedding text
stays on the GM's machine. A local Ollama install and the multilingual
`qwen3-embedding:0.6b` model are required. OCR uses installed Poppler and Tesseract
language data. No model service call occurs in the Core.

Validation includes installation/update conflict tests, provisional-note isolation,
permission/revocation and changed-source checks, paraphrase retrieval, text and
scanned PDF citations, and CLI/MCP coverage. The qualitative conversation pilot
with a live GM remains to be run; deterministic checks alone cannot establish
conversational quality.

## Product intent

SecondChair supports a human GM who creates, maintains, and plays a tabletop campaign over the long term. It supports the GM's creative work; it does not act as an AI GM.

A campaign creation session can have any goal the GM chooses. One session may explore a world or a location; another may work on player characters, how they meet, a prologue, or a first quest. The tool must support an open-ended creative process rather than require a fixed campaign-creation workflow or deliverable.

The shared conversation at <https://chatgpt.com/share/6ad76777-178c-83ed-9446-774fe5fffb34> is a useful example of first-session work: discussing character options, bringing the group together in Absalom, and shaping an archaeological first job. It is a pilot example, not a required workflow.

## Domain language

| Term | Meaning |
|---|---|
| Creative session | A GM-directed conversation for creating or developing any part of a campaign. Its goal is chosen per session. |
| Working idea / piste | An unconfirmed possibility, including one the GM likes. It is not campaign canon. |
| Campaign decision | An idea the GM has explicitly confirmed. |
| Canon | Confirmed campaign truth maintained by SecondChair's campaign memory. A source citation alone does not make something canon. |
| Campaign skill | A SecondChair-provided, workspace-level Agent Skill that guides an agent's work in a campaign. |
| Source | A registered reference file or directory, such as a PDF rulebook or setting book. |

## Delivery requirements

### 1. Add the SecondChair campaign workshop skill

**Goal:** Give supported agents a shared protocol for open-ended campaign creation and maintenance.

Acceptance criteria:

- The skill is authored and versioned in the SecondChair repository and installed as a workspace-level skill in every campaign created by SecondChair.
- The skill is intrinsically part of SecondChair's campaign workflow and is available to supported agent hosts (initially Codex and Claude Code).
- The GM can also install or update the managed skill in an existing workspace through an explicit SecondChair command.
- The installed copy is managed/versioned by SecondChair. Updates do not silently overwrite local edits; campaign-specific skills and instructions can coexist separately.
- The skill supports creation, ongoing campaign maintenance, and session play support while keeping the GM as decision-maker and avoiding an AI-GM role.
- The skill writes campaign content in the campaign language.

### 2. Define the creative conversation protocol

**Goal:** Make the agent a flexible creative collaborator instead of a rigid form or content generator.

Acceptance criteria:

- The GM can start with a fragment, a question, a document, or a specific task and choose a different goal each session.
- The agent helps clarify an unclear goal through discussion; it does not impose a fixed sequence, mandatory questionnaire, or required output.
- The agent uses a mixed posture: it asks focused questions and proposes concrete ideas, normally one question at a time.
- The GM can follow tangents and change the session goal at any time.
- The agent periodically recaps confirmed decisions, tentative ideas, rejected ideas and open questions in an editable summary.
- The agent tactfully points out contradictions or uncertainty and asks the GM to resolve them rather than resolving them silently.
- Task-specific skills can add focused guidance for different kinds of work without replacing the shared collaboration protocol.

### 3. Keep working ideas and canon distinct

**Goal:** Preserve creative exploration without accidentally committing it to campaign memory.

Acceptance criteria:

- Working ideas are retained in campaign notes when the GM asks or approves that workflow; liking a suggestion does not confirm it.
- Notes can be organized by theme and preserve open questions and rejected directions, including the GM's reason when available.
- The agent can update working notes during a session and show the GM an editable recap.
- A proposed change to canon is not applied until the GM explicitly confirms it.
- The agent reports which notes or canon files it actually changed and does not claim chat text was saved.
- A cited source can inform a proposal but cannot silently override canon. Conflicts are shown with their provenance for the GM to resolve.

### 4. Register, browse and search campaign sources

**Goal:** Let the GM see existing campaign material and consult registered external references, including PDFs.

Acceptance criteria:

- The GM can register a single file or a directory of sources in a campaign workspace.
- The GM can see the registered sources and search across campaign material and sources.
- PDF contents can be indexed locally for semantic search across the full document.
- Local indexing and sending relevant excerpts to a model are separate per-source permissions. Neither permission is implied by registering a source.
- An agent uses authorized search, returns relevant passages with source filename and page/location citations, and sends only permitted excerpts to a model.
- When a source changes, SecondChair reports the change and asks before replacing its existing index.
- Search evidence does not automatically amend campaign notes or canon; disagreements with campaign canon are surfaced for the GM.

## Pilot and sequence

Use the shared Absalom first-adventure conversation as a qualitative pilot for issues 1–3. The GM should be able to begin from a loose idea, decide what the session is for, explore character/group/prologue/first-job directions, and leave with a clear distinction between decisions, working ideas, and open questions. Use a different session goal in a later pilot to ensure the protocol is not tied to first-quest creation.

The campaign skill must continue to disclose any missing local embedding or OCR
prerequisite clearly. Semantic indexing of source passages remains subject to the
GM's local-indexing permission; returning an external source excerpt to the host
agent remains subject to its distinct model-excerpt permission.
