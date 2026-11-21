# Contributing

Thanks for helping. Lafaz prepares emails, reminders and board posts from what people said, so a change that could let
something leave without a person's approval gets extra scrutiny.

## Set up

Python 3.12 and [uv](https://docs.astral.sh/uv/). Docker is needed only to run the container.

```sh
scripts/uji.sh            # creates .venv, installs requirements-dev.txt, runs pytest; no keys, no network
python -m lafaz.eval      # the 24-task eval; needs ANTHROPIC_API_KEY and spends a few cents
```

## Before you open a pull request

- Run `scripts/uji.sh`. CI runs the same script.
- Which tools are reversible and which need approval lives in `config/tools.json`, not in code. A change there, or to the
  approval gate, needs a test that fails without your change.
- Values that can change (limits, prices, samples, page text) live in `config/`. Page text goes in both
  `config/i18n/en.json` and `config/i18n/ms.json` with the same keys.
- Do not edit `docs/MEASURED.md` by hand; run the eval again.
- One topic per pull request; describe how you tested it.

## Reporting security issues

See [SECURITY.md](SECURITY.md).
