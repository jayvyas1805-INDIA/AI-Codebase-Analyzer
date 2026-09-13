# AI-Assisted React Codebase Analysis and Intelligent Issue Explanation System

A tool that scans a React (JSX/JS/CSS) codebase, detects CSS class-name
conflicts and related issues using deterministic static analysis, and uses
an LLM (provider-agnostic — Groq, OpenAI-compatible providers, or a
locally-run [Ollama](https://ollama.com) model, configured via env vars in
`backend/app/config.py`) to explain each issue and suggest fixes — with an
optional chat to ask follow-up questions about a specific issue, and an
experimental deterministic auto-fix pipeline for 3 of the 7 issue types
(see "Auto-fixing" below).

**Scope (MVP):** React projects with `.jsx`, `.js`, `.css` files (including
CSS Modules) only. No TypeScript, no other languages, no auth.

---

## How it works (pipeline)

```
React ZIP
  → Project Scanner            (find .jsx/.js/.css files, skip node_modules etc.)
  → CSS Parser                 (tinycss2 — selectors, declarations, line numbers)
  → JSX Parser + Import Resolver  (Babel via a small Node helper — className usage, imports)
  → Codebase Relationship Model   (links CSS definitions ↔ JSX usages ↔ imports)
  → Static Analysis / Issue Detection   (pure deterministic rules, no LLM;
                                          Tailwind utility conflicts are
                                          detected separately, same-element
                                          rather than cross-file — see below)
  → RAG                        (ChromaDB + Ollama embeddings — retrieves relevant context)
  → LLM                        (Ollama chat model — explains issues, on demand)
  → React Dashboard            (upload, issue list, detail view, AI chat)
```

Issue types detected:

| Type | Meaning | Severity |
|---|---|---|
| `css_conflict` | Same class, 2+ files, fully confirmed reachable from the same app, every shared property disagrees | High |
| `partial_overlap_class` | Same class, conflicting properties, but not fully confirmed (or only some properties disagree) | Medium if the conflict is substantial and touches a layout/visual property, otherwise Low |
| `duplicate_class` | Same class, 2+ files, properties agree (or don't overlap) | Low |
| `undefined_css_class` | Used in JSX, no matching CSS rule anywhere | Medium |
| `unused_css_class` | Defined in CSS, never used as a static className in JSX | Low/Medium* |
| `unimported_css_file` | CSS file parsed but never imported by any JS/JSX file | Low |
| `tailwind_utility_conflict` | 2+ Tailwind utilities on the SAME element, same responsive/state variant scope, setting the same CSS property to different values (e.g. `className="p-4 p-2"`) | Medium |

\* Confidence and severity drop for `unused_css_class` if the project uses
dynamic classNames anywhere (e.g. `clsx()`, ternaries) — we can't be fully
sure a class isn't applied conditionally at runtime.

**Low-severity issues are hidden by default.** `/api/scan` only returns
medium/high severity issues in `issues`/`total_issues` — pass
`?include_low=true` to get everything. Low-severity findings are still
fully computed and cached either way, so `/api/explain` and `/api/chat`
work on them even when hidden from the default response.

**CSS Modules (`*.module.css`) are supported**: classes are hashed
uniquely per file by the bundler, so they're excluded from cross-file
conflict/duplicate/unused detection entirely (they structurally can't
collide). The `:global(...)` escape hatch is still treated as a normal
global class and goes through full conflict detection, since it's the one
deliberately un-scoped case that CAN actually collide.

---

## Project structure

```
project/
├── backend/            FastAPI + Python — scanning, parsing, analysis, RAG/LLM
│   ├── app/             all backend source
│   ├── js_helper/        Node/Babel script the Python backend calls for JSX parsing
│   ├── sample_project/    a tiny fixture React project used by the test scripts
│   ├── test_*.py           standalone test scripts (no server needed) for each phase
│   └── requirements.txt
└── frontend/            React + Vite — upload UI, dashboard, chat
    └── src/
```

---

## One-time setup

### 1. Install Python 3.11+ and Node.js 18+
Both should already be on your machine if you've followed this project's
build so far. Check with:
```
python --version
node --version
```

### 2. Choose an LLM provider

The steps below set up **Ollama** (free, local, no API key) since that's
this project's default — but `backend/app/config.py` reads
`LLM_PROVIDER`/`LLM_MODEL`/`LLM_API_KEY`/`LLM_BASE_URL` from the
environment, so any OpenAI-compatible provider (Groq, OpenAI, Together,
Fireworks, ...) works by setting those env vars instead of installing
Ollama at all. If you're using a hosted provider, skip to step 4.

Download Ollama from **https://ollama.com** and install it (Windows/Mac/Linux
installer, a few clicks). It runs automatically in the background after
install.

### 3. Pull the two models this project uses
```
ollama pull llama3.2:1b
ollama pull nomic-embed-text
```
`llama3.2:1b` (~1.3 GB) is the chat model used for explanations and chat.
`nomic-embed-text` (~274 MB) powers the RAG retrieval step. Together
that's about **1.6 GB** of disk — chosen deliberately small. If you have
a bit more space and want noticeably better-quality explanations, you can
switch to `llama3.2:3b` (~2 GB) instead — just change `OLLAMA_CHAT_MODEL`
in `backend/app/config.py` and re-pull.

### 4. Set up the backend
```
cd backend
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Mac/Linux

pip install -r requirements.txt

cd js_helper
npm install
cd ..
```

### 5. Set up the frontend
```
cd frontend
npm install
```

---

## Running the project

You need **three things running** at once, each in its own terminal:

**Terminal 1 — Ollama** (usually already running after install; if not):
```
ollama serve
```

**Terminal 2 — Backend:**
```
cd backend
venv\Scripts\activate
uvicorn app.main:app --reload
```
Runs on **http://127.0.0.1:8000**. Visit `/docs` for interactive API docs.

**Terminal 3 — Frontend:**
```
cd frontend
npm run dev
```
Runs on **http://localhost:5173** — open this in your browser.

---

## Using it

1. Zip up a React project (or use `backend/sample_project` — zip that folder
   as a quick test).
2. Open http://localhost:5173, drag in the zip, click **Analyze Project**.
3. You'll land on the dashboard: summary stats, a filterable issue list,
   and a detail panel.
4. Click any issue — an AI explanation and recommendation generate
   on-demand (this is what makes analysis itself fast even on big projects:
   the scan returns instantly, and the LLM only runs for issues you
   actually look at).
5. Use the chat panel next to the detail view to ask follow-up questions
   about that specific issue.

---

## Testing without the frontend

Each backend phase has a standalone test script that runs against the
bundled `sample_project` fixture — useful for confirming a phase works in
isolation:

```
cd backend
venv\Scripts\activate
python test_scanner.py          # Phase 1: file scanning
python test_css_parser.py       # Phase 2: CSS parsing
python test_jsx_parser.py       # Phase 3: JSX parsing + import resolution
python test_issue_detector.py   # Phase 4: full static analysis pipeline
python test_rag_explain.py      # Phase 5: RAG + LLM explanation (needs an LLM provider configured)
python test_scope_aware_conflicts.py     # reachability-based conflict classification
python test_reachability_fallback.py     # unresolved-app-boundary edge case (regression)
python test_css_modules.py               # CSS Modules support
python test_tailwind_conflicts.py        # Tailwind utility-conflict detector
python test_ai_rename_suggester.py       # LLM-assisted fix naming (mocked LLM, no provider needed)
python test_fix_patch.py                 # fix planning + patch generation
```

You can also test the live API directly via `/docs`, or with curl:
```
curl -X POST http://127.0.0.1:8000/api/scan -F "file=@sample_project.zip"
```

---

## API endpoints

| Endpoint | Method | What it does |
|---|---|---|
| `/` | GET | Health check |
| `/api/scan` | POST | Upload a zip, get back all detected issues (fast — no LLM calls). Query param `include_low` (default `false`) controls whether low-severity issues are included. |
| `/api/explain/{job_id}/{issue_id}` | POST | Generate the AI explanation + recommendation for one issue (cached after first call) |
| `/api/chat/{job_id}/{issue_id}` | POST | Send a chat message scoped to one issue; body: `{"message": "..."}` |
| `/api/plan-fix/{job_id}/{issue_id}` | POST | Deterministically plan a fix (rename or consolidate) for a `css_conflict`/`partial_overlap_class`/`duplicate_class` issue — see "Auto-fixing" below |
| `/api/generate-patch/{job_id}/{issue_id}` | POST | Turn a fix plan into an actual line-level patch |
| `/api/validate-patch/{job_id}/{issue_id}` | POST | Sandbox-validate a generated patch before applying it |
| `/api/fix/{job_id}/{issue_id}` | POST | Run plan → generate → validate → apply in one call |

**Auto-fixing scope:** only `css_conflict`, `partial_overlap_class`, and
`duplicate_class` are fixable — `isolated_duplicate` is explicitly
excluded (two same-named classes proven NOT to interact shouldn't be
touched), and `unused_css_class`/`undefined_css_class`/
`unimported_css_file`/`tailwind_utility_conflict` don't have an automated
fix strategy yet. The fix planner and patch generator are fully
deterministic (blast-radius-based file selection, word-boundary-safe
regex patching, refuses to guess on ambiguous matches) — the LLM's only
role in this pipeline is suggesting a more descriptive replacement class
name than the mechanical `{filename}-{classname}` default, and even that
suggestion is validated and deduplicated by plain Python before it's ever
used, not trusted as-is.

**Note on jobs:** analyzed projects are cached in memory, keyed by `job_id`.
This resets if you restart the backend — you'll need to re-upload and
re-scan after a restart before `/api/explain` or `/api/chat` will work
against that job again.

---

## Known limitations (intentional MVP scope)

- **CSS selector support**: only simple class selectors (`.foo`, `.foo.bar`)
  and CSS Modules' `:global(...)` wrapper. Descendant selectors, IDs, tags,
  and pseudo-classes are recorded but excluded from conflict/usage analysis.
- **CSS Modules**: supported for the common case (`import styles from
  './x.module.css'`, `styles.foo` / `styles['foo']`, including inside
  `clsx()`/ternaries). Re-exported/aliased module imports and SCSS module
  nesting are not yet handled.
- **Tailwind**: a separate same-element utility-conflict detector (not
  part of the cross-file reachability engine — see `tailwind_conflicts.py`)
  catches classes that set the same CSS property with different values in
  the same variant scope (e.g. `p-4 p-2`). It only classifies utilities in
  a specific, deliberately conservative set of property families
  (spacing, sizing, display, position, flex alignment, z-index,
  font-weight/size, text-align, text/background/border color,
  border-radius, opacity, overflow) — an unrecognized utility is silently
  skipped rather than guessed at. No styled-components support.
- **Dynamic classNames**: best-effort extraction from `clsx()`, template
  literals, ternaries, `&&`, and CSS Modules member expressions. Genuinely
  dynamic values (a bare variable, an unrecognized function call) can't be
  resolved to a class name.
- **In-memory job cache**: no database — restarting the backend clears
  all analyzed jobs.
- **No authentication or rate limiting**: `/api/scan` and friends are
  open to anyone who can reach the server, including LLM-calling
  endpoints — do not deploy this publicly as-is.
- **Auto-fixing covers 3 of 7 issue types** (see "Auto-fixing" above) and
  hasn't been run against a large real-world codebase yet — treat
  generated patches as a starting point to review, not a black box to
  trust blindly.

## Explicitly out of scope (per project spec)

No support for Python/Java/C++ codebases, no VS Code extension, no GitHub
integration, no authentication, no multi-agent system, no fine-tuning, no
enterprise features.