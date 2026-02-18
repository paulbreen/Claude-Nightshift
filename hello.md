# Claude Task Runner

Claude Task Runner is an autonomous AI-powered development pipeline that picks up software tasks from GitHub Issues and drives them through a complete development lifecycle — from requirements triage all the way to merged pull request — with minimal human involvement.

## What It Does

The runner polls for GitHub Issues labelled `claude` and `ready`, then orchestrates four specialised AI personas to complete each task:

1. **Product Owner** — Triages the issue, refines requirements, and asks clarifying questions if needed.
2. **Architect** — Designs the implementation plan and reviews code once development is complete.
3. **Developer** — Writes the code inside an isolated git worktree using Claude CLI in autonomous mode.
4. **QA** — Validates the implementation against acceptance criteria, runs tests, and merges the pull request.

All communication between personas happens as GitHub Issue comments, providing a full, human-readable audit trail for every task.

## Key Features

- **End-to-end automation** — from `GitHub Issue` to merged `Pull Request` without manual intervention.
- **Visible audit trail** — every decision, plan, and review is recorded as an issue comment.
- **Safety limits** — configurable caps on daily tasks, review cycles, QA iterations, and execution timeouts.
- **Scheduling** — supports once, daily, weekly, and monthly recurring tasks; optional night-only processing.
- **Containerised** — runs as a Docker container on Unraid or any Docker-compatible host.

## Technology

Built with Python 3, the GitHub API, and [Claude CLI](https://docs.anthropic.com/claude/docs/claude-cli). Packaged as a Docker image for easy self-hosting.
