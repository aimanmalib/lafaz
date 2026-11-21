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
