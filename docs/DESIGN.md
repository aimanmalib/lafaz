# Lafaz design brief

Level: polished. A distinct identity of its own, not a template. Read this before touching any template or stylesheet.

## Subject, audience, job

- Subject: what a person said out loud, and the work that follows from it. The raw material is spoken text: run-on, corrected
  mid-sentence, mixed English and Malay.
- Audience: a team lead who just finished a stand-up or a call and dictated a messy update with Wispr Flow. Hackathon judges see
  the same screens.
- Primary job: show that every item Lafaz extracted is backed by the speaker's own words, and that nothing leaves the room until
  a person approves it.

## The one memorable thing

The **marked transcript**. The words the person said are set large, in a reading serif, and each extracted item paints its proof
directly onto those words like a highlighter on a printed transcript. Decision, action, question and fact each own one marker
colour. A corrected statement is struck through with the label "you corrected this". Everything else on the page stays quiet so
the marks carry the screen.

On `/` the same idea appears before any run: the dictation box is the transcript sheet itself, the person's text in the reading
serif, not a grey form field.

## Tokens

Colour (light). Every colour in CSS comes from these custom properties; no raw hex outside `:root` blocks.

| Token | Hex | Role |
|---|---|---|
| `--ink` | `#17233F` | Text and the wordmark. Deep indigo, the colour of a fountain pen, not black. |
| `--sheet` | `#FBFCFE` | Transcript sheet. Blue-white paper. |
| `--desk` | `#E9EEF6` | Page background around the sheet. |
| `--rule` | `#C9D3E3` | Lines between regions, input borders. |
| `--muted` | `#55617A` | Secondary text. Passes 4.5:1 on `--sheet` and `--desk`. |
| `--mark-decision` | `#FFD54A` | Highlighter, decision. |
| `--mark-action` | `#7FE0C9` | Highlighter, action item. |
| `--mark-question` | `#F7A8CF` | Highlighter, open question. |
| `--mark-fact` | `#C6C3FF` | Highlighter, fact. |
| `--seal` | `#A3261B` | Irreversible actions only: the approval card edge and the Approve button. Never decoration. |
| `--focus` | `#2B5BD7` | Keyboard focus ring. |

Dark mode (`prefers-color-scheme: dark`): `--ink #E6ECF7`, `--sheet #18213A`, `--desk #10172A`, `--rule #2F3B58`, `--muted #A5B0C7`,
`--seal #FF8A7A`, `--focus #8FB0FF`. Marker colours stay the same hue but are used as a translucent underlay (mix 45 %) so text keeps
contrast on the dark sheet.

Type.

- Literata (OFL, self-hosted 400, 400 italic, 600): the spoken words. Transcript, dictation box, quotes, the wordmark.
  Body size 1.25rem on the sheet, line-height 1.6, measure at most 62ch.
- Atkinson Hyperlegible Next (OFL, self-hosted 400, 700): interface. Buttons, chips, labels, tables. 1rem, line-height 1.45.
- Scale (ratio 1.25): 0.8, 1, 1.25, 1.563, 1.953, 2.441 rem. Headings use Literata 600 in sentence case. No all-caps labels,
  no tracked-out eyebrows, no monospace data labels.

Space: 4 px base; steps 4, 8, 12, 16, 24, 32, 48, 64. Radius: 2 px on the sheet and marks (paper is not rounded), 999 px only on
chips and the language switch (they are pills you tap), 6 px on buttons. Shadow: one, on the sheet only, `0 1px 0 var(--rule),
0 12px 32px -16px` in ink at low alpha. Cards do not get shadows.

## Layout

```
desktop /                                  phone /
+------------------------------------------+  +----------------+
| Lafaz            [Rung 3 chip] [EN|BM]   |  | Lafaz   [EN|BM]|
|                                          |  | [Rung 3 chip]  |
|   +----------------------------------+   |  | +------------+ |
|   | sheet: big serif text area       |   |  | | sheet      | |
|   | "Hold your Wispr Flow key ..."   |   |  | |            | |
|   +----------------------------------+   |  | +------------+ |
|   meeting date   [Try a sample] [Plan]   |  | [Try a sample] |
|   one-line promise, muted                |  | [Plan]         |
+------------------------------------------+  +----------------+

desktop /run/<id> (B4)
| Heard (marked transcript) | Understood (items) | Plan (approval cards) |
```

Left aligned throughout. The sheet is centred on the desk with a max width of 46rem on `/`; on `/run` the three columns share
the desk and Heard keeps the serif. On phones the columns stack in reading order Heard, Understood, Plan.

## Motion

One moment only: when a run finishes, the highlighter marks sweep in left to right on the transcript (background-size transition,
240 ms, staggered by item). Respect `prefers-reduced-motion` (no sweep, marks appear at once). No entrance animations on sections,
no hover lift on cards.

## Banned here

- `backdrop-filter` and animated `filter` anywhere (WebKit crashes); sticky glass headers.
- Cream background with a terracotta accent; near-black with an acid accent; identical rounded cards with grey shadows.
- Middle-dot meta strings, arrows appended to button text, emoji, all-caps labels, gradient washes.
- The seal colour on anything that is not an irreversible action.
- Any text in templates: all copy lives in `config/i18n/en.json` and `config/i18n/ms.json`.

## Review against the generic default

First draft used a warm off-white page with an orange accent for "speech". That is the most common generated look, so it was
replaced with blue-white paper on an indigo ink, where the colour comes from the four highlighter markers that carry meaning.
A draft with a monospace face for the trace drawer was dropped too: the trace uses the interface face with tabular numbers.

## Quality floor

WebKit iPhone 13 and 320 px wide with no horizontal scroll (`scrollWidth <= clientWidth`), visible focus ring two layers at most,
tap targets at least 44 px, `lang` attribute follows the selected language, light and dark both checked.
