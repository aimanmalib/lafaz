# Decisions

Short records of choices made while building Lafaz. Newest last. Each one says what, why, and how to undo it.

## D1. Stack: FastAPI, Jinja2, HTMX, SQLite (21 Nov, 15:40 MYT)

- What: Python 3.12, FastAPI with Jinja2 templates, HTMX 2.0.11 vendored as a file in `static/vendor/`, SQLite in WAL mode.
  No JavaScript build step.
- Why: one container, server-rendered pages that work on a phone, and a stack that can be built and tested inside one day.
- Undo: the app is a single package (`lafaz/`); templates and static files are separate, so a different front end can replace them.

## D2. Pinned dependencies (21 Nov, 15:40 MYT)

- What: `requirements.txt` holds every runtime package at an exact version, compiled with `uv pip compile` for Python 3.12.
  `requirements-dev.txt` adds pytest and httpx. Direct pins: fastapi 0.165.0, uvicorn 0.54.0, jinja2 3.1.6,
  python-multipart 0.0.34, anthropic 2.12.0.
- Why: the container built at 01:00 must match the one tested at 16:00.
- Undo: change a pin and recompile.

## D3. Claude API reference loaded before any LLM code (21 Nov, 15:42 MYT)

- What: the Claude API reference skill was loaded in the builder session before the LLM adapter exists. Points that shape the
  adapter, written down so later slices follow them:
  - The model comes from `config/lafaz.json` (`llm.model`, currently `claude-sonnet-5-5`).
  - On that model, forced `tool_choice` (`any` or a named tool) returns HTTP 400. The adapter uses `tool_choice: auto`,
    `strict: true` on every tool schema, and a prompt that names the tool to call.
  - Thinking cannot be turned off with `disabled` on that model; depth is set with `output_config.effort` (config `llm.effort`).
  - Always check `stop_reason` before reading content, including `refusal`; the server-side fallback (`llm.fallbacks`) is
    sent with the documented beta flag.
  - Tool inputs are parsed as JSON objects, never matched as strings.
  - Unit tests use a fake client; the real API is used only by the eval runner and the live demo.
- Why: the SDK changed shape in 2026 and guessing its API costs more time than reading the reference.
- Undo: not applicable; this is a working rule.

## D4. Fonts self-hosted (21 Nov, 15:45 MYT)

- What: Literata and Atkinson Hyperlegible Next, latin subsets only, served from `static/fonts/` with their OFL licence files.
- Why: no third-party CDN at runtime (privacy, and the demo must work if a CDN is blocked).
- Undo: delete the `@font-face` rules; the stacks fall back to system fonts.

## D5. Language choice order (21 Nov, 15:45 MYT)

- What: `?lang=` wins, then the `lafaz_lang` cookie, then the default in config. Choosing a language through `?lang=` sets
  the cookie for a year.
- Why: a judge can share a link in either language, and the choice sticks while they click around.
- Undo: change `lang_cookie_days` or remove the cookie write in `lafaz/app.py`.

## D6. One container behind the host proxy (21 Nov, 16:15 MYT)

- What: `deploy/deploy.sh` builds HEAD from a clean `git archive`, runs one read-only container (0.75 CPU, 384 MB) with
  the SQLite file on the named volume `lafaz-data`, and installs a Traefik file route with `compress`. HTML carries
  `Cache-Control: no-cache, no-transform` so the CDN does not recompress it. Host values sit in `deploy/hos.env` and the
  deploy tags in `deploy/*_TAG`, both untracked. Keys reach the container only through the optional `LAFAZ_ENV_FILE`.
- Why: a single small process is enough for a judged demo, and a clean archive guarantees that ignored files (keys,
  state, notes) never reach the image.
- Undo: `deploy/deploy.sh --rollback` runs the previous image, which a stopped `lafaz-undo` container holds.

## D7. Listen layer: the model proposes, code decides (21 Nov, 16:55 MYT)

- What: one Messages API call with the strict `record_items` tool (schema in `config/tools.json`), then code in
  `lafaz/listen/` checks everything the model returned:
  - Quotes: spaces, case and typographic quote marks are normalised; each quote must be a substring of the input and at
    least `min_quote_words` words (`config/listen.json`). A correction counts only when both quotes exist and the old one
    comes first. A failing item is rejected and stored with its reason code (`items.status = 'rejected'`).
  - Owners: a named owner must match exactly one known person by full name, first name or alias. An action with no
    named owner belongs to the speaker only when the quote is in the first person ("I'll", "saya"). Anything else is a
    question.
  - Dates: the model returns the deadline words, never a date. Code resolves them from the meeting date with the word
    lists in `config/listen.json`. A plain weekday is the next one after the meeting; "next Friday" and "Jumaat depan"
    mean that weekday in the following Monday-to-Sunday week. Vague words ("soon", "next week") and impossible dates
    become a question.
  - Questions written by code are stored as a code plus parameters and shown through `question.*` keys in the
    interface text files, so they appear in English or Malay.
- Request shape follows D3: `tool_choice: auto`, `strict: true`, effort and model from config, server-side fallback,
  `stop_reason` checked before content. Cost is estimated from `config/prices.json`; an unknown model costs 0 rather
  than a guessed number.
- Why: a quote that code can find in the input is the proof a judge can check. Dates and owners decided by code are
  repeatable and testable without a model.
- Undo: `lafaz/listen/` is self-contained; the word lists and the minimum quote length are config.

## D8. Agent loop: a manual tool loop with a permission gate read from config (21 Nov, 17:40 MYT)

- What: `lafaz/agent/` runs one listen call, then a manual Messages API tool loop over the tools marked
  `"stage": "plan"` in `config/tools.json`. Every tool call goes through `lafaz/agent/gate.py`, which reads only
  `kategori`:
  - `read` and `reversible` run; reversible steps keep an undo record (`gate.undo`). A task already published to the
    shared board cannot be undone.
  - `irreversible` never runs from the loop. It becomes a row in `approvals` with a readable diff, and the model is told
    it is waiting. Only `gate.approve` (a person's click) runs it, after checking the arguments again; an edit is
    checked against the same schema; `gate.skip` runs nothing.
  - Owners, dates and recipients come from the checked items, not from the model's arguments. `ask_team` needs a quote
    that code finds in the meeting text.
  - Limits (`run_limits` in `config/lafaz.json`: steps, seconds, cost) are checked before each model call and each
    tool call. Hitting one, a model error, nothing heard, or open questions end the run with a handoff object
    `{reason, done, not_done, questions, quotes}` stored on the run.
  - Every step goes to `steps` with category, arguments (keys in `agent.redact_keys` hidden), result, time, tokens and
    cost. Model turns are steps with category `model`.
  - Email actions write to `outbox` with status `queued`; delivery belongs to the integration layer.
- Why a manual loop rather than the SDK tool runner: the loop must stop on cost and time between calls, record each
  step, and turn some calls into approvals instead of results. The assistant turn is appended unchanged (thinking
  blocks included) and all tool results of a turn go back in one user message, as the API reference requires.
- Measured: one live run on the synthetic sample created 2 tasks and filed 4 approvals (2 reminders, 1 team question,
  1 publish), sent nothing, took about 37 s and cost USD 0.033 by `config/prices.json`.
- Undo: the gate is one module; changing a tool's `kategori` in config changes its behaviour without code.

## D9. Memory and conflicts: code picks candidates, the model judges, a person decides (21 Nov, 17:30 MYT)

- What: `lafaz/memory/` adds people, decisions, conflicts and reminder policies (new tables in `lafaz/schema.sql`,
  `outbox.policy_id` and `outbox.label` by ADD COLUMN; nothing is dropped).
  - Each accepted decision item becomes an active decision. Earlier active decisions from other runs become
    candidates only when they share at least `conflict.min_shared_terms` terms after normalising and removing the
    stopwords in `config/memory.json`. The model is never asked about a pair code did not pick.
  - The model judges each pair with `judge_conflict` (strict schema in `config/tools.json`). Code checks the old quote
    against the old meeting text and the new quote against the new one. A failed check is stored as `rejected` with
    its reason; a model error or a spent budget is stored as `not_judged`. Only `conflict` verdicts open a card.
  - Card buttons map to tools in `conflict.choices`: Replace (`replace_decision`) and Keep both
    (`keep_both_decisions`) are `reversible` and can be undone; Ask the team is `ask_team`, `irreversible`, so it
    waits for approval. These tools have `"stage": "card"`, so the agent loop never sees them, and the gate still
    decides from `kategori`.
  - Approving `send_reminder` now approves a policy. The scheduler, an asyncio task inside the app (no outside daemon),
    runs every `scheduler.reminder_check_seconds`. It sends only to the task owner, from the send day to the due date,
    at most `reminders.max_sends_per_policy` times, never twice on one day, and stops when the task is done or undone.
    Each send carries the label `approved_once` ("Approved once, runs within limits").
  - Owners and speakers heard in a run are remembered as people; the next run's listen call receives them.
- Measured: one live `judge_conflict` call on two synthetic meetings reported the conflict with both quotes accepted
  by code, in about 19 s, USD 0.004 by `config/prices.json`.
- Undo: the memory step is two lines in `lafaz/agent/loop.py`; removing them leaves the loop as in D8.
