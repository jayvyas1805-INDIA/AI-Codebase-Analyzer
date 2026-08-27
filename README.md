# AI-Assisted React Codebase Analysis and Intelligent Issue Explanation System

A tool that scans a React (JSX/JS/CSS) codebase, detects CSS class-name
conflicts and related issues using deterministic static analysis, and uses
a locally-run open-source LLM (via [Ollama](https://ollama.com)) to explain
each issue and suggest fixes — with an optional chat to ask follow-up
questions about a specific issue.

**Scope (MVP):** React projects with `.jsx`, `.js`, `.css` files only.
No TypeScript, no other languages, no auth, no auto-fixing code.

---

## How it works (pipeline)

```
React ZIP
  → Project Scanner            (find .jsx/.js/.css files, skip node_modules etc.)
  → CSS Parser                 (tinycss2 — selectors, declarations, line numbers)
  → JSX Parser + Import Resolver  (Babel via a small Node helper — className usage, imports)
  → Codebase Relationship Model   (links CSS definitions ↔ JSX usages ↔ imports)
  → Static Analysis / Issue Detection   (pure deterministic rules, no LLM)
  → RAG                        (ChromaDB + Ollama embeddings — retrieves relevant context)
  → LLM                        (Ollama chat model — explains issues, on demand)
  → React Dashboard            (upload, issue list, detail view, AI chat)
```

Issue types detected:

| Type | Meaning | Default severity |
|---|---|---|
| `css_conflict` | Same class, 2+ files, every shared property disagrees | High |
| `partial_overlap_class` | Same class, 2+ files, some properties agree/disagree | Medium |
| `duplicate_class` | Same class, 2+ files, properties agree (or don't overlap) | Low |
| `undefined_css_class` | Used in JSX, no matching CSS rule anywhere | Medium |
| `unused_css_class` | Defined in CSS, never used as a static className in JSX | Low/Medium* |
| `unimported_css_file` | CSS file parsed but never imported by any JS/JSX file | Low |

\* Confidence and severity drop for `unused_css_class` if the project uses
dynamic classNames anywhere (e.g. `clsx()`, ternaries) — we can't be fully
sure a class isn't applied conditionally at runtime.

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

### 2. Install Ollama (the local, open-source LLM runtime)
Download from **https://ollama.com** and install it (Windows/Mac/Linux
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
python test_rag_explain.py      # Phase 5: RAG + LLM explanation (needs Ollama)
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
| `/api/scan` | POST | Upload a zip, get back all detected issues (fast — no LLM calls) |
| `/api/explain/{job_id}/{issue_id}` | POST | Generate the AI explanation + recommendation for one issue (cached after first call) |
| `/api/chat/{job_id}/{issue_id}` | POST | Send a chat message scoped to one issue; body: `{"message": "..."}` |

**Note on jobs:** analyzed projects are cached in memory, keyed by `job_id`.
This resets if you restart the backend — you'll need to re-upload and
re-scan after a restart before `/api/explain` or `/api/chat` will work
against that job again.

---

## Known limitations (intentional MVP scope)

- **CSS selector support**: only simple class selectors (`.foo`, `.foo.bar`).
  Descendant selectors, IDs, tags, and pseudo-classes are recorded but
  excluded from conflict/usage analysis.
- **CSS sourcing**: plain CSS files only — no CSS Modules, no Tailwind
  utility-class awareness, no styled-components.
- **Dynamic classNames**: best-effort extraction from `clsx()`, template
  literals, ternaries, and `&&`. Genuinely dynamic values (a bare variable,
  an unrecognized function call) can't be resolved to a class name.
- **In-memory job cache**: no database — restarting the backend clears
  all analyzed jobs.
- **Single chat model quality**: `llama3.2:1b` is small and occasionally
  won't follow the "Explanation / Recommendation" format perfectly; the
  code degrades gracefully (falls back to putting everything under
  Explanation) rather than breaking.

## Explicitly out of scope (per project spec)

No support for Python/Java/C++ codebases, no VS Code extension, no GitHub
integration, no authentication, no multi-agent system, no fine-tuning, no
automatic code modification, no enterprise features.
