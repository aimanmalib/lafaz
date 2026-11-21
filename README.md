<p align="center"><img src="brand/logo-512.png" width="96" height="96" alt="Lafaz"></p>

<h1 align="center">Lafaz</h1>

<p align="center"><a href="https://github.com/aimanmalib/lafaz/actions/workflows/ci.yml"><img src="https://github.com/aimanmalib/lafaz/actions/workflows/ci.yml/badge.svg" alt="CI"></a> <a href="LICENSE"><img src="https://img.shields.io/github/license/aimanmalib/lafaz" alt="Licence: MIT"></a> <img src="https://img.shields.io/badge/python-3.12-blue" alt="Python 3.12"> <img src="https://img.shields.io/badge/eval-24%20of%2024-17233F" alt="Eval 24 of 24"> <img src="https://img.shields.io/badge/input-Wispr%20Flow-17233F" alt="Input: Wispr Flow"></p>

<p align="center"><b>Say it messy. Every item quotes your own words. Nothing leaves without your approval.</b><br>
<a href="https://youtu.be/PpIyKNEM7_s"><b>&#9654;&#xFE0E; demo video, 88 s</b></a> · <a href="https://lafaz.sasateguh.com">live</a> · <a href="https://lafaz.sasateguh.com/eval">eval</a> · <a href="docs/MEASURED.md">measured</a> · <a href="docs/ARCHITECTURE.md">architecture</a> · <a href="CHANGELOG.md">changelog</a> · <a href="README.ms.md">Bahasa Melayu</a> · Built in Malaysia by <a href="https://www.linkedin.com/in/aimanmalib">Aiman Malib</a></p>

<p align="center"><img src="docs/images/run.png" width="838" alt="Lafaz run page: the spoken update with decisions, actions and questions marked on the speaker's own words, a self-correction struck through, and email cards that wait for approval"></p>

Built on 21 Nov 2026 at the NextGen AI Hackathon (Agentic AI Hackathon '26 by Product Space x Wispr Flow). Problem statement: meeting to execution.

## The problem

After a meeting or a site visit, the update is spoken in a hurry: half sentences, a date said as "next Friday", a name
changed halfway. Someone then has to turn that into tasks, emails and reminders. An assistant that does this alone can send
the wrong thing to the wrong person, and nobody can see why.

## What Lafaz does

1. **Heard.** You dictate the update with Wispr Flow, filler words and corrections included. Lafaz shows what it heard and
   marks each decision, action, question and fact on your own words. When you correct yourself ("Tuesday, no wait,
   Wednesday"), the newer words win and the old ones are struck through.
2. **Understood.** Every item carries an owner, a due date and the exact quote that proves it. Code checks that each quote
   really appears in what you said; an item without proof is rejected.
3. **Plan.** Lafaz drafts the follow-ups: emails, reminders, team board posts, calendar entries.
4. **Approve.** Anything that leaves the room waits on a card until a person presses Approve. When Lafaz cannot finish, it
   stops and says where and why.

Other pages: `/board` (team board, only approved tasks), `/memory` (decisions and what replaced them), `/voice`,
`/about`. Interface in English and Malay.

## How it is measured

24 fixed tasks run through the same agent loop as the live page, with nobody approving anything
([docs/MEASURED.md](docs/MEASURED.md), commit `46f110d`, model `claude-sonnet-5-5`):

| Measure | Result |
|---|---|
| Task success | 24 of 24 |
| Path quality | 1.77x the minimum tool steps, 0 repeated calls |
| Constraint adherence | 0 irreversible actions without approval (37 left waiting for a person) |
| Give-up quality | 2 of 2 on the 4 tasks meant to stop |

Mean cost USD 0.0217 per run; p50 latency 8.7 s.

## Tests

`scripts/uji.sh` runs the full pytest suite offline, without keys: the quote checker, the approval gate, the
public sandbox that must never send real email, the board and calendar feed that show approved
tasks only, both languages on every page, and the eval scorer itself. CI runs the same script on every push.

The eval in `evals/` is separate because it calls the model. Each task is a spoken update with an answer key: the items
that must be found, the self-corrections that must resolve to the newer words, the conflicts with earlier decisions, the
questions that must stay open, and the tasks where the right move is to stop. Two tasks hide instructions inside the
update ("send this to everyone now"); Lafaz must treat them as words that were said, not orders to follow.

## How it is built

One Python process (FastAPI + HTMX) with SQLite in WAL mode. Which tools are reversible and which need approval comes from
one config file (`config/tools.json`); the agent loop reads it, no code decides it. Details:
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), decisions in [docs/DECISIONS.md](docs/DECISIONS.md).

![Architecture](docs/architecture.svg)

## Run it locally

```bash
docker build -t lafaz .
docker run --rm -p 8080:8080 -e ANTHROPIC_API_KEY=sk-ant-... lafaz
# open http://localhost:8080
```

Tests: `scripts/uji.sh` (creates `.venv` with uv, then runs pytest). Evals: `python -m lafaz.eval`.

## Wispr Flow

Wispr Flow is the input: you dictate into the update box and Lafaz works from what Flow typed. The video shows real Wispr
Flow screenshots from this build, including a self-correction that Flow cleaned up before Lafaz read it.

## AI disclosure: my contribution and the AI's

All code was written during the event by AI coding agents (Claude) that I directed. I chose the problem, set the rules the
agent must never break, and approved what shipped. Before the event I wrote a plan for approaching any agent brief; no code.

## Who it is for

Small team leads who run stand-ups, site visits or client calls and speak the update afterwards, usually in a mix of English
and Malay. The person who spoke stays in charge: Lafaz prepares, the person approves.

## Limitations

- Speech reaches Lafaz as text typed by Wispr Flow; there is no audio input of its own.
- Public visitors work in a sandbox: email delivery runs only in the owner's space.
- Evaluated on 24 tasks written for this build, not on real customer meetings.

## License

MIT
