# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project overview

KaoyanVocab — a minimalist vocabulary collection system for Chinese graduate entrance exam (考研) preparation. Workflow: encounter unknown words during practice → paste into web page or right-click in browser → DeepSeek API auto-fills meaning, examples, POS, and derivatives (with automatic lemmatization) → stored in local SQLite → review with flashcards → export to PDF via Cmd+P on weekends.

## Start / dev

```bash
pip install -r requirements.txt  # fastapi, uvicorn, requests, python-dotenv
python main.py                   # starts server on http://127.0.0.1:8000
open http://127.0.0.1:8000       # open frontend in browser (served by the backend at GET /)

# Or use the restart script (kills existing process, starts in background, logs to server.log, opens the browser):
bash restart.sh
tail -f server.log               # watch logs

# Windows 11: double-click start.bat (or run start-server.ps1) — checks Python/deps,
# kills whatever listens on port 8000, starts the server minimized, opens the browser.
```

Opening the frontend at `http://127.0.0.1:8000` makes API calls same-origin. Opening `index.html` via `file://` still works too (CORS still allows the `null` origin).

## Architecture

Three components, no build tools:

- **`main.py`** — FastAPI backend. Uses `lifespan` context manager to run `init_db()` on startup. SQLite auto-creates `vocab_data.db`. CORS restricted to `null` (file:// pages), localhost, and browser-extension origins; an Origin-checking middleware hard-403s all other origins (CSRF / API-credit abuse guard).
- **`index.html`** — Pure HTML/JS/CSS frontend. No frameworks. Fetches from `http://127.0.0.1:8000`. PDF export via CSS `@media print` + browser's Cmd+P.
- **`browser-extension/`** — Chrome Manifest V3 extension. Adds right-click context menu to collect selected English text from any webpage. Injects a toast notification: a persistent "正在提交..." loading toast that stays until the request completes, then becomes a success/failure toast. The toast also shows the current model (fetched from `/api/provider`). Install via `chrome://extensions` → "Load unpacked".

## .env format

```
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com        # optional, defaults to this
MIMO_API_KEY=sk-xxx                                # Xiaomi MiMo (OpenAI-compatible)
MIMO_BASE_URL=https://api.xiaomimimo.com           # optional origin; /v1/chat/completions appended
MIMO_MODEL=mimo-v2.5                               # optional, defaults to this
```

Never commit `.env`.

## API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/words` | List all entries, newest first. Supports `?important=true` filter |
| POST | `/api/words` | Create entry. Body: `{expression, skip_spell_check, provider}`. Normalizes to lemma form automatically via the selected provider |
| GET | `/api/words/{id}` | Get single entry |
| PATCH | `/api/words/{id}` | Update fields (expression, pos, meaning, example_en, example_cn, derivatives) — used by inline editing |
| DELETE | `/api/words/{id}` | Delete an entry |
| PATCH | `/api/words/{id}/important` | Toggle important flag (`{is_important: bool}`) |
| GET | `/api/suggest?q=word&provider=deepseek` | Spell-check only via the selected provider, returns `{correct, suggestions}` |
| GET | `/api/provider` | Returns the shared active provider (`deepseek` \| `mimo-fast` \| `mimo`) |
| POST | `/api/provider` | Sets the shared active provider. Body: `{provider}`. Persisted to `provider_state.json` |
| GET | `/api/words/latest-id` | Returns `{latest_id}` — used by frontend auto-refresh polling |
| GET | `/api/words/due` | Returns today's review list. Auto-assigns on first call. Adaptive target 100–300 (based on last 7 days' accuracy/volume); important words force-included first, overdue by priority score, new words interleaved |
| GET | `/api/words/assigned-today` | Returns `{count}` of unreviewed words assigned today |
| POST | `/api/words/{id}/review` | Record SM-2 review. Body: `{quality: 1\|5}`. Returns next review scheduling |
| GET | `/api/review-stats` | Dashboard stats: today's reviewed/due/accuracy, streak, total reviews |

## LLM integration (DeepSeek + Xiaomi MiMo)

Two providers, both OpenAI-compatible, switchable at runtime via the `provider` field (`deepseek` | `mimo-fast` | `mimo`) on `/api/words` and `/api/suggest`. The frontend selector is in the capture toolbar; the selection persists in `localStorage` (`vocab_provider`).

The backend also keeps a **shared active provider** (`/api/provider`, persisted to `provider_state.json`). The web UI pushes its selection to this endpoint on load and on change, and requests that omit `provider` (the browser extension) fall back to the shared active provider — so the extension always follows the manual-input selection.

- **DeepSeek** — model `deepseek-v4-flash`, base `https://api.deepseek.com`.
- **MiMo 快速** (`mimo-fast`) — model `mimo-v2.5` with `thinking: disabled`; no reasoning, ~2-3s.
- **MiMo 深度思考** (`mimo`) — model `mimo-v2.5` with `thinking: enabled`; higher quality but slower. A reasoning model, so `call_llm()` gives it a 60s timeout.

Three system prompts:

- **`UNIFIED_PROMPT`** — Combined spell-check + vocabulary expert. Used when `skip_spell_check=false` (Enter key path). Returns `{spell_check, lemma, pos, meaning, example_en, example_cn, derivatives}`.
- **`SYSTEM_PROMPT`** — Vocabulary expert only, no spell check. Used when `skip_spell_check=true` (button click path, browser extension).
- **`SUGGEST_PROMPT`** — Spell checker only, used by `/api/suggest`.

**Lemmatization**: Both UNIFIED_PROMPT and SYSTEM_PROMPT instruct DeepSeek to normalize inflected forms to base/dictionary form (lemma). The `lemma` field is used as the stored `expression`. Examples: `running`→`run`, `went`→`go`, `upped their game`→`up their game`. Falls back to original input if `lemma` is missing.

The `call_llm()` helper routes by provider, handles API call, markdown fence stripping, JSON parsing, and retry/backoff.

**Lemmatization tuning**: The system prompts contain a detailed decision tree to prevent the LLM from over-reducing fixed phrases (e.g. `take it for granted` should not be reduced to `take`). Multi-word phrases only get external tense/number normalization, never internal morphology stripped.

## Frontend features

### Word input flow

1. **Enter key** → `checkAndAdd()` → POST with `skip_spell_check=false` (UNIFIED_PROMPT). If spell check fails, shows a modal with suggestions. User picks one or uses original.
2. **Button click** → `addWord()` → POST with `skip_spell_check=true` (SYSTEM_PROMPT), skipping spell check. Used for phrases or when confident.
3. **Browser extension** → right-click selected text → POST with `skip_spell_check=true` → toast notification on page.

The suggest API is fire-and-forget on failure — falls back to direct add.

### Flashcard system (背单词)

Opens a full-screen overlay with setup screen to choose study count (50/100/150/200/all). Words are selected sequentially from the list (not randomized). Keyboard controls: **Q** = known (quality 5), **E** = unknown (quality 1, auto-marks as important), **Space** = next, **R** = back, **Esc** = exit. Supports dark mode toggle. Words marked unknown get `is_important` flag set via API (fire-and-forget). Clicking the card also advances. Records SM-2 review data via `/api/words/{id}/review`.

### Daily Review mode (每日复习)

Uses SM-2 spaced repetition. Words are assigned daily with an adaptive target of 100–300, derived from the last 7 days' accuracy (70%) and average daily volume (30%); falls back to 100 with no history. Important words (`is_important`) are force-included first; overdue words are ranked by priority score (important +50, overdue days ×2, ease-factor deficit ×20, failure count ×15, never-passed +10); never-reviewed words are interleaved evenly among review words. Keyboard: **Q** = known (quality 5), **E** = forgot (quality 1), **Space** = confirm & next, **R** = back, **Esc** = exit. Shows next review interval after each card. Badge on button shows unreviewed count. Opening the review shows a toast with the day's composition (新词 N · 复习 M).

### Bookmark (书签)

Single global bookmark stored in `localStorage` (key: `vocab_bookmark`, value: `{id, time}`). Each row has a 📌 button — click to set, click again to remove. Setting a new bookmark auto-removes the old one. Bookmarked row gets left blue border. Toolbar has "跳转至书签" button that smooth-scrolls to the row with a flash highlight.

### Other features

- **Hide meanings (隐藏释义)** — Toggle button blurs the meaning column (`filter: blur(6px)`) for self-testing recall. Hover reveals temporarily; click permanently unblurs that cell.
- **Star marking (重点标记)** — Star button toggles `is_important` via PATCH. Important rows get a yellow tinted background (`row-important` class). Star persists in PDF export. Filter with `?important=1` URL param.
- **Search** — Search bar with fuzzy matching on both expression and meaning. Shows match count.
- **Inline editing** — Double-click any cell to edit. Enter/Esc to save/cancel. Derivatives edited as JSON.
- **Auto-refresh** — Polls `/api/words/latest-id` every second. If a new word was added (e.g., via browser extension), the table refreshes automatically.

## Database

SQLite at `vocab_data.db`. Two tables:

**`vocabulary`** — main word table:
- `derivatives` stored as JSON text, parsed back to array on read
- `is_important` flag (0/1) — toggled via star button, used for flashcard unknown marking
- `created_at` is unix timestamp, used for DESC ordering
- SM-2 fields: `repetition`, `ease_factor`, `interval`, `next_review` (ISO date), `last_review`, `assigned_date`

**`review_log`** — review history: `word_id` (FK), `reviewed_at` (unix timestamp), `quality` (1 or 5)

No migration system — columns added via `ALTER TABLE ... ADD COLUMN` with try/except in `init_db()`. Delete the `.db` file to reset schema. `vocab_data.db` and `server.log` are runtime artifacts, not source.

## PDF export

No server-side PDF generation. Frontend uses `@media print` CSS to hide `.no-print` elements, enforce black text, add table borders in `pt` units, and `page-break-inside: avoid` on rows. User presses Cmd+P in browser.
