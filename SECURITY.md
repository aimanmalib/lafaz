# Security policy

## Reporting a vulnerability

Please use [private vulnerability reporting](https://github.com/aimanmalib/lafaz/security/advisories/new). It reaches
only the maintainer. Don't open a public issue for a security problem.

Include what you found, how to reproduce it, and what an attacker could do with it. You will get a reply within seven
days.

## Supported versions

Only the latest commit on `main` gets fixes.

## What matters most here

- **The approval gate.** Any path that lets an irreversible action (an email, a board post, a reminder) run without a
  person's approval is a vulnerability, including prompt injection in the spoken update.
- **The owner's space.** Real email delivery is only for the owner's space; a public visitor reaching it is a vulnerability.
- **Keys.** `ANTHROPIC_API_KEY` and SMTP credentials are read from the environment and must never appear in logs, pages or
  eval results.
