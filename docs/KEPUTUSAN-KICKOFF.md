# Kickoff decision: which problem statement Lafaz answers

Status: **Meeting-to-execution agent (statement 03 of the 21 Nov list).**
First recorded 21 Nov 2026, 15:24 MYT (07:24 UTC) as a default. Confirmed 15:31 MYT (07:31 UTC) against the 21 Nov text.

## Where the statement text comes from

| Time (UTC) | Source | Result |
|---|---|---|
| 07:21 | Organizer page "ai-hackathon-details/problem-statement" | HTTP 200, still shows the 31 Oct edition. Not accepted. |
| 07:21 | Organizer page "ai-hackathon-details" | HTTP 200, still shows the 31 Oct edition. Not accepted. |
| 07:21 | Unstop competition API | No change to dates, prizes, rounds or submission requirements. |
| 07:25 | Organizer page "agentic-ai-hackathon/problem-statement" (new address), copied by the owner's side during the kickoff | Five statements dated 21 Nov. Accepted. Polling stopped. |

## Selection rule (fixed before the event)

Each statement is scored 0 to 2 on five axes. Weight in brackets.

1. The agent takes at least one irreversible action that a human must approve (x3).
2. Speech is the natural main input (x3).
3. Every required item can be built in 7 hours with no new account, no GPU and no heavy media (x3; a 0 here removes the statement).
4. Quality can be measured with at least 24 tasks that have fixed answers (x2).
5. The builder has a real story about the problem (x1).

Highest score wins. A tie goes to the statement with fewer required items, then to the organizer's order. If the 31 Oct
Meeting-to-execution statement is repeated, it is chosen.

## Scores (21 Nov statements, organizer numbering)

| Axis (weight) | 03 Meeting-to-execution | 04 Personal finance coach | 02 Exam-prep tutor | 05 Career pivot coach | 01 Content repurposing |
|---|---|---|---|---|---|
| Irreversible action (x3) | 2 | 1 | 1 | 1 | 1 |
| Speech is main input (x3) | 2 | 2 | 2 | 2 | 0 |
| Buildable in 7 h (x3) | 2 | 1 | 1 | 1 | 0 (removed) |
| Measurable, 24+ tasks (x2) | 2 | 2 | 1 | 1 | 1 |
| Real story (x1) | 2 | 1 | 0 | 1 | 1 |
| **Total (max 24)** | **24** | **17** | **14** | **15** | removed |

The 21 Nov list repeats the 31 Oct statements, so the scores carry over. 01 needs long video or podcast ingestion, which is heavy media.

**Choice: Meeting-to-execution agent.** It is the only statement where every required item has an irreversible step a person should
approve, and spoken updates are already how teams report work.

## Required item map (21 Nov wording, verbatim)

The organizer text: "Decisions made in meetings get lost." and "The cross-meeting memory and the conflict detection are what make
this a real system rather than a transcript summarizer."

| Required item (verbatim) | Module | Tool (category) | Eval tasks |
|---|---|---|---|
| transcript ingestion with speaker attribution | `lafaz/listen` (code parses `Name: text`) | `record_items` (read) | extraction |
| extraction of decisions, action items, owners, and deadlines | `lafaz/listen`, quote checker, date resolver | `record_items` (read), `create_task` (reversible) | extraction, give-up (unclear owner) |
| detection of conflicts with earlier decisions stored in memory | `lafaz/memory` (code picks candidates) | `judge_conflict` (read), `ask_team` (irreversible) | conflict |
| creation of tasks in a tracker through an integration | `lafaz/board` (internal board, CSV and JSON export) | `publish_to_board` (irreversible) | extraction |
| reminders before deadlines | in-process scheduler, approved-once policy | `send_reminder` (irreversible) | give-up (limit reached) |
| a weekly digest per person | `lafaz/summary` | `preview_summary` (reversible), `send_summary` (irreversible) | extraction |
| a confirmation step before anything gets posted | `lafaz/agent` approval gate, category read from config | every irreversible tool | adversarial (instructions inside a transcript) |

## Judging rubric (21 Nov)

Prototype quality and UX 25, AI integration 25, Problem understanding 20, LinkedIn content and engagement 15, Innovation and
creativity 15, plus a LinkedIn engagement bonus. The choice and the architecture do not change. Build order favours the run screen
and the agent loop, which carry the two largest lines.

## Not built, and why

- Jira, Linear or Slack connectors: they need accounts and OAuth that cannot be set up inside one day. The internal board exports
  CSV and JSON instead.
- Browser microphone and own speech-to-text: Wispr Flow already types the speech into the text box.
- User accounts: one public sandbox space and one private owner space.

## Owner notice

- 07:24 UTC: owner asked to send the 21 Nov statement text from the kickoff call. Silence means the build continues with
  Meeting-to-execution.
- 07:31 UTC: owner told the 21 Nov choice. Replying with another statement number within 20 minutes switches it; silence means
  the build continues.
