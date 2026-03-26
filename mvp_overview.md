# Skill Updater MVP overview 

summary of the current Skill Updater MVP implementation in this repository.

It is written as a system module view (not a standalone app):

- Skill Updater writes structured knowledge into Skills Core.
- Skill Bot and PR Dashboard consume Skills Core.
- This MVP focuses on the Skill Updater interaction boundary and internal pipeline.

Reading guide:

- Each shape text is written as an action plus expected output.
- Boxes show processing steps.
- Diamond shapes show mandatory checks or branch decisions.
- Right-most boxes usually represent user-facing or system-level impact.

---

## 1) End-to-End MVP (System Fit)

```mermaid
flowchart LR
  A[Run updater from CLI or scheduler job] --> B[Fetch only maintainer Discord messages with time window]
  B --> C[Load current Skills Core files from SKILLS_DIR of that repo]
  C --> D[Run embedding relevance filter to keep only useful files]
  D --> E[Build strict JSON prompt from messages plus selected files]
  E --> F[Generate structured JSON edits using local Ollama model]
  F --> G[Apply safe patch operations to skill files]
  G --> H[Persist updated Skills Core knowledge on filesystem]
  H --> I[Enable better Skill Bot answers and PR Dashboard reasoning]
```

Description:

- This is the top-level loop your organization needs to understand.
- The updater does not answer users directly; it improves shared context quality.
- Value path is: maintainer knowledge from Discord -> structured skill updates -> better downstream AI behavior.
- Treat this as a knowledge maintenance pipeline, not a chatbot runtime.

---

## 2) Internal Pipeline (Code-Level Flow)

```mermaid
flowchart TD
  A[Validate required env vars and parse runtime flags] --> B[Resolve analysis date range from days or from-to inputs]
  B --> C[Fetch Discord messages then remove low-signal noise text]
  C --> D[Load files from SKILLS_DIR with extension and size checks]
  D --> E[Score each file using embeddings and cosine similarity threshold]
  E --> F[Build strict JSON-only prompt with files plus message context]
  F --> G[Call Ollama generate endpoint for edit proposal]
  G --> H[Parse response JSON and attempt repair for common format issues]
  H --> I{Dry-run mode or no changes needed?}
  I -- Yes --> J[Exit safely after summary or preview output]
  I -- No --> K[Apply edits and append operational logs]
```

Description:

- This matches the actual orchestration in `main.py`.
- The only probabilistic stage is LLM generation; all downstream steps are guarded.
- Most production risk is controlled after generation by strict parse and patch guards.
- Even when model output is imperfect, the pipeline prefers safe failure over unsafe writes.

---

## 3) Data Flow (What Moves Through the System)

```mermaid
flowchart LR
  M[Discord raw messages from configured channel] --> MF[Filter noise and attach reply-parent context]
  S[Skill files from local Skills Core folder] --> SF[Scan files and truncate oversized content safely]
  MF --> Q[Build query text from meaningful maintainer content]
  Q --> QE[Create single query embedding vector]
  SF --> FE[Create per-file embedding vectors for comparison]
  QE --> SIM[Compute cosine similarity scores]
  FE --> SIM
  SIM --> SEL[Select relevant files based on threshold rules]
  SEL --> P[Assemble prompt with selected files and message evidence]
  MF --> P
  P --> LLM[Receive model JSON text response]
  LLM --> J[Extract edits array with summary metadata]
  J --> W[Write approved patch actions to filesystem]
```

Description:

- Inputs are two streams: maintainer messages and current skill files.
- Relevance filtering reduces prompt size and keeps updates targeted.
- Output is structured edits, not free-text suggestions.
- The important design choice is structure over prose: JSON edits are easier to validate than natural-language suggestions.

---

## 4) Runtime Sequence (Interaction by Module)

```mermaid
sequenceDiagram
  actor U as User/Scheduler
  participant M as main.py
  participant D as discord_fetcher.py
  participant DR as Discord API
  participant P as skill_patcher.py
  participant O as ollama_client.py
  participant OL as Ollama API
  participant FS as Skills Filesystem

  U->>M: run updater command
  M->>D: fetch_messages(start,end)
  D->>DR: request paginated channel messages
  DR-->>D: return message batches
  D-->>M: return filtered maintainer messages
  M->>P: load_skills_folder()
  M->>P: find_relevant_files()
  P->>O: request embeddings(query plus file snippets)
  O->>OL: call embeddings endpoint
  OL-->>O: return embedding vectors
  M->>O: generate(prompt)
  O->>OL: call generation endpoint
  OL-->>O: return raw JSON text
  M->>P: apply_edits(edits)
  P->>FS: persist file updates
```

Description:

- This clarifies ownership: `main.py` orchestrates, helpers are single-purpose.
- Discord and Ollama are external dependencies.
- Skill storage remains plain files, preserving git-native review and rollback.
- Sequence view is best for understanding call order and boundaries.
- Component view (Section 6) is best for understanding long-term maintainability.

---

## 5) Component Architecture (Current MVP Boundaries)

```mermaid
flowchart TD
  subgraph Core[Skill Updater Core]
    MAIN[main.py orchestrates end-to-end run lifecycle]
    CFG[config.py loads env values and validates required settings]
    DF[discord_fetcher.py fetches messages and removes noise]
    PB[prompt_builder.py builds strict JSON generation prompt]
    OC[ollama_client.py wraps generate and embedding API calls]
    SP[skill_patcher.py selects files and applies deterministic edits]
  end

  DIS[Discord API message source] --> DF
  DF --> MAIN
  MAIN --> PB
  MAIN --> OC
  MAIN --> SP
  SP --> OC
  SP <--> SK[Skills Core Files as shared context storage]
  OC --> OLL[Ollama API for embeddings and generation]
  SK --> SB[Skill Bot consumes updated knowledge]
  SK --> PR[PR Dashboard consumes updated reasoning context]
```

Description:

- `config.py` centralizes environment + validation constants.
- `discord_fetcher.py` owns Discord pagination, author filtering, and noise removal.
- `skill_patcher.py` owns both relevance selection and deterministic patch operations.
- Skills Core remains the shared contract with the rest of your org architecture.
- If you need one maintenance entry point, start from `main.py` then inspect each module in call order.

---

## 6) Integration View (Org-Level Interaction)

```mermaid
flowchart LR
  SU[Skill Updater module in unified org system] --> DC[Discord maintainer discussions as trusted input]
  SU --> OL[Local Ollama inference for private processing]
  SU --> SC[Skills Core repository as central knowledge layer]
  SC --> SB[Skill Bot runtime uses context for contributor answers]
  SC --> PR[PR Dashboard uses context for maintainer decision support]
  FUT[Future integration extension point] --> GH[GitHub PR and event signals]
  GH --> SU
```

Description:

- This positions the MVP in the broader organization ecosystem.
- Current integration is stable and file-based.
- Future webhook/event integration can be added without replacing the core updater pipeline.

---

## 7) Key info

1. Maintainer-only message filtering is enforced by Discord author ID matching.
2. Reply-parent context is fetched and attached to improve interpretation.
3. Noise filtering removes low-signal chat text before model invocation.
4. File scanning uses extension allowlist plus max-size truncation guard.
5. Relevance stage uses embeddings + cosine threshold and always includes primary skill file.
6. Prompt builder requests strict JSON-only edits with explicit schema-like structure.
7. JSON parser includes repair attempts for common malformed model output.
8. Edit engine supports `create`, `append_section`, `append_end`, `replace` with guardrails.
9. Dry-run path exists for preview without file mutation.(even include in attach tutorial)