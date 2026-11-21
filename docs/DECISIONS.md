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
  `outbox.policy_id` and `outbox.label` by `ADD COLUMN`; nothing is dropped).
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

## D10. Run page: a worker thread, HTMX polling, and marks mapped back to the spoken words (21 Nov, 17:55 MYT)

- What: `POST /run` stores the meeting, starts `lafaz.agent.loop.run` in a worker thread (`lafaz/runner.py`) and
  redirects to `/run/<id>`. While the run is `started` the page body polls `/run/<id>/body` every
  `run_page.poll_seconds`. Buttons (Approve, Edit then approve, Skip, Undo, conflict choices) post forms to
  `lafaz/routes_run.py`; with HTMX the body is swapped, without JavaScript the browser is redirected back (303).
- Why a thread and not one long request: a run may take up to `run_limits.max_seconds` (90 s), close to the
  proxy and CDN limits, and a person should see progress. A thread inside the app keeps the "no outside daemon"
  rule; a run left `started` by a restart is closed at start-up with the reason `interrupted`.
- Live runs need the model key named by `llm.key_env` in the environment. Without it `POST /run` stores nothing and
  says live planning is off (PRD 4.10: the public URL is replay mode until the owner's key arrives). Budget and
  per-IP limits come in C5.
- Marks: the quote checker matches normalised text. `lafaz/view/marks.py` rebuilds that normalisation one source
  character at a time with an index map, so a mark covers the words exactly as typed (curly apostrophes, case,
  spacing), and a quote that is not in the text is never painted.
- Edit before approving offers the top-level string and integer fields of the tool's schema; the gate checks the
  edited arguments again. A failed check keeps the card pending only for schema errors (D8).
- Measured: one live run of the synthetic sample: 4 items, 2 tasks created, 4 cards waiting, stopped with
  `missing_facts` because one question stayed open; 67 s, USD 0.032.
- Undo: remove `app.include_router(run_router)`; the run routes disappear and the dictation page still works.

## D11. Eval: fixed tasks through the real loop, scored from the database (21 Nov, 18:45 MYT)

- What: `evals/tasks/*.json` (one file per task, file name = id) are checked by `lafaz/eval/tasks.py` before any
  model call. `python -m lafaz.eval` runs each task in its own temporary SQLite file through `lafaz.agent.loop.run`
  with the real model (threads: `eval.workers`), scores it in `lafaz/eval/score.py`, saves
  `evals/results/<UTC time>.json` and rewrites `docs/MEASURED.md`. `/eval` shows the newest results file.
- Why from the database: the four measures must describe what Lafaz did, not what the model said it did. Task
  success needs every expected item (kind, words, owner, resolved date), correction, question, required tool and
  stop. Constraint adherence counts irreversible steps that executed plus approvals marked approved, because no
  person is present during an eval; any count above 0 makes the command exit 1.
- Path quality is tool steps over the task's own `min_steps`. Extra plan calls that only file approvals count as
  steps, so the ratio is honest rather than flattering.
- The first run found two real faults, both fixed with regression tests: a supporting quote under three words
  ("Will do") rejected a whole item that had a full quote (now the short quote is dropped, an item with only short
  quotes is still rejected), and "for Friday" / "Friday the 27th" were not resolved (now `for` is a filler word and a
  weekday with a date resolves only when both agree).
- The results commit is recorded; `+uncommitted` is added when code, config, prompts or tasks differ from it.
- Undo: remove `app.include_router(eval_router)` and the `eval` block in `config/lafaz.json`; nothing else reads them.

## D12. Public limits and replay mode (21 Nov, 20:30 MYT)

- What: live runs on the public site stop at `public_budget.usd_per_day` (a run in progress counts at
  `run_limits.max_cost_usd`) and at `public_budget.runs_per_ip_per_day` per visitor, both per UTC day
  (`lafaz/budget.py`). The visitor address comes from `cf-connecting-ip` only when the hop the host proxy saw is in
  `public_budget.cloudflare_ranges`; it is stored as a 16-character hash of day and address, never raw.
- Replay: without a key, or once a limit is reached, a sample with a cassette (`replay` in `config/samples.json`,
  file in `evals/replay/`) still runs. The cassette holds the model's responses from one real run; `lafaz/replay.py`
  hands them to the real loop, so the quote checker, dates, gate, approvals and actions all run as they do live. The
  run is stored with mode `replay`, costs nothing and says so on the run page. It plays only for the exact text and
  meeting date it was recorded for (line breaks normalised); anything else gets a notice and is not stored.
- Ids: rows made during a replay get new ids. The ids the model saw in recorded tool results are matched with this
  run's results, and later recorded tool inputs (`*_id`, `*_ids`) are rewritten, so a recorded answer never points
  at another run's rows. A request the recording cannot answer fails as `model_error:replay_unrecorded`.
- Memory: a decision from a meeting with the very same text is not a conflict candidate. Without this, every second
  try of a sample would ask the model to judge a decision against itself.
- Record again after a prompt, tool or sample change: `python -m lafaz.replay record <sample-id>` with the key set.
- Undo: delete `evals/replay/` and the `replay` field; the site falls back to the "not live" notice.
