# Knowledge ingestion and retrieval: done, left, leaves

Design note for [#190](https://github.com/Hugo-Grellier/SecondChair/issues/190) (ingest owned PF2e PDFs and Foundry compendia into a permissioned source catalog) and [#191](https://github.com/Hugo-Grellier/SecondChair/issues/191) (hybrid PF2e/Golarion retrieval with an evidence-backed graph). No code. Read against `main` at `e96207e`, 2026-10-20.

Risk classes used below: **R0** docs, tests or bench only; **R1** behaviour change inside existing invariants; **R2** touches a trust, licence, secrecy or data-loss boundary and needs a GM-approved ADR first.

## What #149 and #158 already deliver

#149, the reference library ([spec 12](../spec/12-campaign-creation-and-library.md), [workspace contract](../contracts/workspace-layout.md#campaign-workshop-and-reference-library-spec-12-first-delivery), `src/secondchair/core/library.py`):

- **Per-source registration.** `register` (`library.py:81`) snapshots one file or a directory of PDF, Markdown or text files. The id is derived from the resolved path. `library.yaml` in the workspace maps ids to filenames. Paths and permissions live in machine configuration (`library/<workspace-path-hash>.json`).
- **Two separate permissions per source.** `index` (local extraction and embedding) and `model` (excerpts may reach an agent host) are set by `permit` (`library.py:117`). Both are GM gestures with no MCP tool. Purchased content with `opt_in: false` (LIC-12) also blocks model excerpts (`library.py:489`).
- **A machine-wide hybrid index.** One SQLite file holds every campaign's sources, keyed by content SHA-256 and embedding model (`_db`, `_store`). FTS5/BM25 requires every query term. Cosine similarity over 256-dimension `qwen3-embedding:0.6b` vectors comes from the GM's Ollama (ADR 0001 amendment). The two are fused by reciprocal rank (`search`, `library.py:468`).
- **Extraction.** `pdftotext` runs in reading order, with Tesseract OCR for pages that have no text (`_passages`, `_ocr_page`). Passages of about 1,500 characters are packed within a page and cited by physical page or line.
- **Freshness and consent.** A changed source or model is reported. Replacing the index needs `--replace-changed` from an interactive terminal. A failed extraction keeps the old index.
- **Guarding job inputs.** A raw registered path cannot be a job input (`guard_job_inputs`, `library.py:572`). Purchased paths become metadata-only indexes (`jobs._licensed`, `jobs.py:100`).

#158, Foundry reads and prepared documents (`src/secondchair_foundry/tools.py`, `foundry/secondchair-foundry/scripts/documents.js`), verified live on Foundry 14.369:

- `search_compendium` (`tools.py:357`) does a live name-substring search over the GM's installed packs. It returns `{uuid, name, type, pack, img, level, rarity, traits}` (`documents.js:308-404`).
- `official_name` (`tools.py:382`) maps a slug or English key to the installed, translated name and an `official_reference` (CAN-20/21).
- `browse_files`, `image_size` and `list_world_documents` provide reads. `prepare_document` writes desired JournalEntry, Actor, Item, Playlist and RollTable state, with `@prepared` references and reconciliation.

So #190's skeleton exists: registration, separate local and model permissions, page citations, change approval, OCR, and live compendium lookup by UUID. #191's first two tiers exist: exact names through BM25, and hybrid through RRF. Neither issue is done. What is left follows.

## What is left

| Gap | Today | Needed | Issue |
|---|---|---|---|
| Edition, version and language metadata | A source is a filename and a digest | Per source: publisher title, edition (legacy or remaster), printing or errata version, language, product id. GM-entered or read from the PDF metadata, shown in citations | #190 |
| Structure-aware extraction | Fixed-size passages; no headings; tables and stat blocks flattened in reading order | Use the PDF outline (`pdfinfo -struct` or bookmarks) for heading paths. Detect stat blocks (the PF2e `CREATURE n` / trait line / AC-HP-saves shape) and tables as atomic chunks with a layout pointer. Use vision repair only on pages flagged by a cheap heuristic (low text density, broken column flow) | #190 |
| Stable chunk identity across re-import | Passages keyed by `(digest, rowid)`; a new printing gets new ids and the old ones remain until deleted | A chunk id derived from `(source, heading path, ordinal)`, plus a re-import diff of added, removed and changed chunks so citations survive errata | #190 |
| Compendium metadata index | Live query only, while a GM client is open, by name substring | An offline, read-only snapshot of pack metadata: pack, UUID, slug, type, level, rarity, traits, publication (`system.publication.title`, `remaster`), system version and translation name. Taken at handshake, so lookups work without Foundry and a system upgrade is detected (by diffing snapshots). Content stays in Foundry: metadata only, under LIC-12 | #190 |
| Authority classes | Facts carry rank (`played`, `gm_decision`, `agent_proposal`; ADR 0007/0008). Library hits carry `kind: source / canon / notes / sessions` only | One `authority` label on every retrieved item: `official_rules`, `official_lore` (edition-tagged), `purchased_ap`, `house_canon` (fact rank ≥ gm_decision), `played`, `working_idea` (notes/), `contradiction`. Search never merges classes; a canon-vs-source disagreement is returned as a pair | #191 |
| Player-context gating | Search reads `canon/`, `notes/` and `sessions/` whole (`library.py:476`) and returns GM secrets to any caller; there is no player context | A `context: gm / party / <pc>` parameter, resolved before ranking: for canon, the existing knower filter (`index.search_knowledge`); for sources, a per-source `audience` (`gm-only` by default, `player-safe` opt-in). Applied in SQL, before any text leaves the index | #191 (R2) |
| Revocation and invalidation | Revoking `model` stops retrieval; the index is retained | It already holds for retrieval. A future derived graph needs edges keyed by chunk id, so that a revocation or re-import invalidates them deterministically | #191 |
| Selective entity/relation extraction | None. The ADR 0001 amendment keeps extraction as a job | A playbook (`extract-source-entities`, standard tier) that writes **candidates** quoting chunk ids into a review queue, never canon (CAP-style; #168 gates the rank) | #190/#191 |

### Is a graph warranted?

Not yet. Multi-hop questions ("which deity's clergy runs the Westerhold harbour guild") are answered today by the host chaining `search_campaign_library` calls (ADR 0001 amendment). Canon already has typed relations and a knower graph in SQLite (`index.py`, `mystery.py`). Add a source-entity graph only if the benchmark below shows that hybrid plus agent chaining misses multi-hop answers the graph would find. If one is added, use SQLite adjacency tables in the existing machine-wide index, keyed by chunk id. Not Neo4j: it would break local-first and single-process (#184).

A local-search survey from 2026-10-20, kept as an uncommitted research snapshot outside this repository, supports this. It reached four conclusions:

- **[Graphify](https://github.com/Graphify-Labs/graphify) is not a passage index.** It extracts a knowledge graph with no embeddings and no vector store. It extracts from documents through the configured model backend, which may be remote, and its documentation shows no OCR or scanned-PDF support. So it can at most complement a lore graph. It cannot replace cited passage retrieval, and its extraction would have to respect the `model` permission (ADR 0001 amendment: extraction is a job).
- **Embedded vector stores were compared:** [Qdrant local mode](https://qdrant.tech/documentation/quickstart/), [Chroma PersistentClient](https://docs.trychroma.com/docs/run-chroma/cloud-client), [LanceDB](https://docs.lancedb.com/) and [sqlite-vec](https://github.com/asg017/sqlite-vec). Qdrant and Chroma position their local modes for small datasets or testing. LanceDB's scope is broader than a campaign library needs. sqlite-vec fits the one-SQLite-file shape, but it is pre-v1 and its extension loading would need validation on the supported OS and Python matrix.
- **Storage and embedding are separate decisions.** Sending passages to a remote embedding service is a different data flow from sending excerpts to a generative model. Today both stay local (Ollama) or are gated by `model`.
- **OCR and page citations** need an explicit validation pass whatever store is chosen.

Implication: keep #149's NumPy-over-SQLite store until the benchmark shows linear vector search is the bottleneck. Its ceiling is about 2–3 s per query at 800k passages. sqlite-vec is then the smallest step that keeps one file.

## Benchmark plan (R0, private corpus)

- **Corpus**: the GM's own PF2e PDFs, with GM Core/Player Core and one Lost Omens setting book as a minimum, plus one purchased AP. Stored in `secondchair-bench-private` and referenced by a configured path (BEN-06). Never in CI.
- **Gold set**: about 60 questions written by the GM. 20 exact rules lookups (spell, condition, feat; the answer is a page). 15 stat-block or table lookups (a creature's AC or a treasure-table row). 15 multi-hop lore questions. 5 that no entitled source answers (abstention is expected). 5 canon-versus-source contradictions. Each has its expected source, page and authority class.
- **Arms**: lexical only, hybrid (today), hybrid with structure-aware chunks, and hybrid with a graph neighbourhood (only if built).
- **Metrics**: recall@5 and MRR on the expected page, citation precision, abstention correctness, contradiction surfacing, p50/p95 latency, index size and indexing time per 100 pages.
- **Leak checks** (gated, never just reported): canaries planted in a `gm-only` source and in GM-secret canon must never appear in `party`-context results or in model-permitted excerpts of a source whose model permission is denied.
- Shares the harness with #172 and #195 (latency floors as data grows).

## Proposed leaf issues

| Title | Scope | Risk | Deps |
|---|---|---|---|
| Source metadata: edition, version, language, product | GM-entered fields on registration, shown in citations, plus PDF metadata defaults | R1 | — |
| Retrieval benchmark on a private PF2e corpus | The plan above, as a bench scenario and report | R0 | — |
| Outline-aware PDF chunking with heading paths | Heading path per passage; chunks never cross headings | R1 | benchmark |
| Stat-block and table extraction as atomic chunks | Detector and layout pointer; an extraction-error report the GM can audit | R1 | outline chunking |
| Stable chunk ids and re-import diff | `(source, heading path, ordinal)` ids; added/removed/changed report on `--replace-changed` | R1 | outline chunking |
| Offline compendium metadata snapshot | Metadata snapshot taken at handshake; a system-version diff; lookup by UUID or slug offline | R1 | — |
| Authority class on every retrieved item | `authority` field; contradiction pairs | R1 | #168 |
| Player-context gating of retrieval | `context` parameter, per-source `audience`, SQL-level filter, canary tests | R2 | ADR; authority class |
| Source-entity extraction into a review queue | A standard-tier playbook writing cited candidates, never canon | R2 | #168, stable chunk ids |
| Graph-assisted retrieval (conditional) | SQLite adjacency over chunk ids, only if the benchmark shows a multi-hop gap | R1 | benchmark, extraction |
