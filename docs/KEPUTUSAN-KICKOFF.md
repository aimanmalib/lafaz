# Kickoff decision: which problem statement Lafaz answers

Status: **default C1 (Meeting-to-execution), statement survey in progress.**
Recorded 21 Nov 2026, 15:24 MYT (07:24 UTC). This file is updated when the 21 Nov problem statements are published.

## Where the statement text comes from

| Time (UTC) | Source | Result |
|---|---|---|
| 07:21 | Organizer page "ai-hackathon-details/problem-statement" | HTTP 200, still shows the 31 Oct edition. Not accepted. |
| 07:21 | Organizer page "ai-hackathon-details" | HTTP 200, still shows the 31 Oct edition. Not accepted. |
| 07:21 | Unstop competition API | No change to dates, prizes, rounds or submission requirements. |

The statements are revealed during the kickoff call (12:30 to 13:30 IST, 15:00 to 16:00 MYT). The pages are checked at most once
every 10 minutes per page, until 17:30 MYT, with a hard limit of 15 requests in total. A screenshot or note from the kickoff call
is accepted as a source.

## Selection rule (fixed before the event)

Each statement is scored 0 to 2 on five axes. Weight in brackets.

1. The agent takes at least one irreversible action that a human must approve (x3).
2. Speech is the natural main input (x3).
3. Every required item can be built in 7 hours with no new account, no GPU and no heavy media (x3; a 0 here removes the statement).
4. Quality can be measured with at least 24 tasks that have fixed answers (x2).
5. The builder has a real story about the problem (x1).

Highest score wins. A tie goes to the statement with fewer required items, then to the organizer's order. If the 31 Oct
Meeting-to-execution statement is repeated, it is chosen.

## Scores

Scored against the 31 Oct statements until the 21 Nov text is available.

| Axis (weight) | Meeting-to-execution | Personal finance coach | Exam-prep tutor | Career switch coach | Content repurposing |
|---|---|---|---|---|---|
| Irreversible action (x3) | 2 | 1 | 1 | 1 | 1 |
| Speech is main input (x3) | 2 | 2 | 2 | 2 | 0 |
| Buildable in 7 h (x3) | 2 | 1 | 1 | 1 | 0 (removed) |
| Measurable, 24+ tasks (x2) | 2 | 2 | 1 | 1 | 1 |
| Real story (x1) | 2 | 1 | 0 | 1 | 1 |
| **Total (max 24)** | **24** | **17** | **14** | **15** | removed |

**Choice: Meeting-to-execution.** It is the only statement where every required item has an irreversible step a person should
approve, and spoken updates are already how teams report work.

## Required item map (31 Oct wording, paraphrased until the 21 Nov text is copied verbatim)

| Required item | Module | Tool (category) | Eval tasks |
|---|---|---|---|
| Transcript with speaker attribution | `lafaz/listen` (code parses `Name: text`) | `record_items` (read) | extraction |
| Decisions, actions, owners, deadlines | `lafaz/listen`, quote checker, date resolver | `record_items` (read), `create_task` (reversible) | extraction, give-up (unclear owner) |
| Conflicts with earlier decisions in memory | `lafaz/memory` (code picks candidates) | `judge_conflict` (read), `ask_team` (irreversible) | conflict |
| Tasks in a tracker through an integration | `lafaz/board` (internal board, CSV and JSON export) | `publish_to_board` (irreversible) | extraction |
| Reminders | in-process scheduler, approved-once policy | `send_reminder` (irreversible) | give-up (limit reached) |
| Weekly summary per person | `lafaz/summary` | `preview_summary` (reversible), `send_summary` (irreversible) | extraction |
| Confirmation before anything is posted | `lafaz/agent` approval gate, category read from config | every irreversible tool | adversarial (instructions inside a transcript) |

## Not built, and why

- Jira, Linear or Slack connectors: they need accounts and OAuth that cannot be set up inside one day. The internal board exports
  CSV and JSON instead.
- Browser microphone and own speech-to-text: Wispr Flow already types the speech into the text box.
- User accounts: one public sandbox space and one private owner space.

## Owner notice

- 07:24 UTC: owner asked to send the 21 Nov statement text from the kickoff call. Silence means the build continues with
  Meeting-to-execution.
