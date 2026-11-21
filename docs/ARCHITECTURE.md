# Architecture

Lafaz is one Python process serving HTML. Speech arrives as text (Wispr Flow types it into the dictation box), the agent turns it
into items with quotes as proof, and anything that leaves the room waits for a person's approval.

```
browser ──HTML/HTMX──> FastAPI (lafaz/app.py)
                          ├── config/*.json, prompts/*.md   values and wording, read at start-up
                          ├── lafaz/db.py                   SQLite in WAL mode (one file, one volume)
                          └── agent layers (later slices)    listen, plan, approve, memory, integrations
```

## Layers

| Layer | Module | Status |
|---|---|---|
| Pages, language switch, health check | `lafaz/app.py`, `templates/` | built |
| Config and interface text | `lafaz/config.py`, `lafaz/i18n.py` | built |
| Storage | `lafaz/db.py`, `lafaz/schema.sql` | built (meetings, runs, steps, items, questions) |
| Listen: quotes, owners and dates checked by code | `lafaz/listen/`, `lafaz/llm.py`, `prompts/listen.md` | built |
| Agent loop with approval gate | `lafaz/agent` | built |
| Memory and conflicts | `lafaz/memory` | built |
| Email delivery (owner space, IMAP check) | `lafaz/mail` | built (D13) |
| Calendar feed, board | `lafaz/integrations` | planned |

The full required item map is in `docs/KEPUTUSAN-KICKOFF.md`.

## Four fixed values

1. **English and Malay from day one.** All interface text is in `config/i18n/en.json` and `config/i18n/ms.json`. A test fails if
   the two files do not have the same keys and placeholders, or if a template uses a key that does not exist.
2. **Product-grade interface.** `docs/DESIGN.md` sets the tokens, type and layout. Pages are checked in WebKit at iPhone 13 size
   and at 320 px wide.
3. **Change without touching code.** Model, limits, budget, rung, timezone, tool categories and samples are in `config/*.json`.
   Prompts live in `prompts/*.md`; eval tasks will live in `evals/tasks/*.json`. Code reads them; code does not hold them.
4. **Small modules, recorded choices, a way back.** Every source file stays under 400 lines. Choices are in `docs/DECISIONS.md`.
   A deploy can be rolled back to the previous image with one command.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `LAFAZ_DB` | `state/lafaz.db` | SQLite file. In the container it points into the `lafaz-data` volume. |
| `LAFAZ_CONFIG_DIR` | `config/` | Folder with `lafaz.json`, `tools.json`, `samples.json`, `listen.json`, `prices.json`, `i18n/`. |
