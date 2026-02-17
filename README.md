# Claude Task Runner

An autonomous AI agent that picks up tasks from GitHub Issues and drives them through a full software development lifecycle using Claude CLI — from triage to merge.

Designed to run as a Docker container on **Unraid** (or any Docker host).

## How It Works

```
You create a GitHub Issue → Claude picks it up → Triage → Design → Develop → Review → QA → Merge
```

The runner uses **four AI personas** that communicate via GitHub issue comments, creating a visible audit trail:

| Persona | Role |
|---|---|
| 🎯 **Product Owner** | Triages issues, refines requirements, asks clarifying questions |
| 🏗️ **Architect** | Designs implementation plans, performs code reviews |
| 💻 **Developer** | Writes code using Claude CLI in YOLO mode |
| 🧪 **QA** | Validates against acceptance criteria, runs tests, merges PRs |

## Quick Start

### 1. Prerequisites

- A GitHub Personal Access Token with `repo` scope
- An Anthropic API key
- Docker (or Unraid)

### 2. Create the Task Repo

Create a new GitHub repo (e.g. `your-username/Claude-ToDo`). This is where you'll create issues that the runner picks up.

### 3. Configure

Copy `config.yaml` and edit it:

```yaml
schedule:
  night_window_start: 2       # Tasks tagged 'night-only' run between these hours
  night_window_end: 8
  timezone: "Europe/London"

polling_interval_minutes: 5

github:
  task_repo: "your-username/Claude-ToDo"
  token: "${GITHUB_TOKEN}"
  human_username: "your-github-username"

claude:
  default_model: "sonnet"
  timeout_minutes: 30
  max_turns: 50

limits:
  max_tasks_per_day: 10
  max_review_cycles: 3
  max_qa_cycles: 2
  stale_days: 7
```

### 4. Deploy

**With Docker Compose:**

```bash
# Create directories
mkdir -p /mnt/user/appdata/claude-task-runner/data
mkdir -p /mnt/user/appdata/claude-task-runner/work

# Copy your config
cp config.yaml /mnt/user/appdata/claude-task-runner/config.yaml

# Set environment variables
export ANTHROPIC_API_KEY="sk-ant-..."
export GITHUB_TOKEN="ghp_..."

# Run
docker-compose up -d
```

**On Unraid:**

1. Build the image or push to a registry
2. Add a new container via the Unraid Docker UI
3. Set environment variables: `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`
4. Map volumes:
   - `/mnt/user/appdata/claude-task-runner/data` → `/data`
   - `/mnt/user/appdata/claude-task-runner/config.yaml` → `/app/config.yaml`
   - `/mnt/user/appdata/claude-task-runner/work` → `/work`

### 5. Create a Task

Create an issue in your `Claude-ToDo` repo with the `claude` and `ready` labels:

```markdown
---
repo: your-username/target-project
new_repo: false
priority: high
schedule: once
night_only: false
---

## Task

Add input validation to the user registration endpoint.

## Context

The registration endpoint is in `src/routes/auth.ts`. It currently
accepts any input without validation.

## Acceptance Criteria

- All fields are validated (email format, password strength, name length)
- Validation errors return 400 with descriptive messages
- Add unit tests for all validation rules
```

The runner will pick it up on its next poll cycle and drive it through the full lifecycle.

## Task Lifecycle

```
ready → triage → design → development → code-review → qa → done
                              ↑              │          │
                              └──────────────┘          │
                              ↑                         │
                              └─────────────────────────┘
```

At any stage, work can be escalated to `awaiting-human` if:
- Requirements are unclear
- Code review has gone through too many cycles
- QA keeps rejecting

You'll be tagged on the issue (`@your-username`) when input is needed.

## Issue Frontmatter Reference

| Field | Type | Default | Description |
|---|---|---|---|
| `repo` | string | *required* | Target repo (e.g. `user/project`) |
| `new_repo` | bool | `false` | Create the repo if it doesn't exist |
| `description` | string | `""` | Repo description (for new repos) |
| `private` | bool | `false` | Make new repo private |
| `priority` | string | `"medium"` | `high`, `medium`, or `low` |
| `schedule` | string | `"once"` | `once`, `daily`, `weekly`, `monthly` |
| `night_only` | bool | `false` | Only process in the night window |
| `human_review` | bool | `false` | Require human approval before merge |
| `group` | string | `null` | Group related tasks |
| `depends_on` | list | `[]` | Issue numbers that must be done first |
| `branch_prefix` | string | `"claude"` | Branch name prefix |

## Labels

The runner manages these labels automatically:

| Label | Meaning |
|---|---|
| `claude` | Issue is managed by the task runner |
| `ready` | Available for pickup |
| `triage` | Product Owner is refining requirements |
| `design` | Architect is creating a plan |
| `development` | Developer is writing code |
| `code-review` | Architect is reviewing the PR |
| `qa` | QA is validating the work |
| `awaiting-human` | Blocked — needs your input |
| `done` | Completed and merged |
| `failed` | Something went wrong |
| `night-only` | Only process in the night window |
| `recurring` | Scheduled to repeat |

## Safety & Limits

- **Daily task cap** — configurable max tasks per day (default: 10)
- **Review cycle cap** — escalates to human after N review rounds (default: 3)
- **QA cycle cap** — escalates to human after N rejections (default: 2)
- **Timeout** — kills Claude CLI if it runs too long (default: 30 min)
- **Max iterations** — prevents infinite stage loops (hardcoded: 20)
- **Graceful shutdown** — handles SIGTERM/SIGINT cleanly

## Monitoring

All activity is logged to:
- **Container stdout** — visible in `docker logs claude-task-runner`
- **`/data/run.log`** — persistent log file
- **GitHub issue comments** — full audit trail on every issue

## Architecture

```
claude-task-runner/
├── main.py              # Entry point + scheduler loop
├── github_client.py     # All GitHub API interactions
├── task_parser.py       # Parse issue frontmatter + body
├── task_runner.py       # Orchestrates the full lifecycle
├── worktree_manager.py  # Git repos, worktrees, branches
├── recurring.py         # Recurring schedule tracking
├── personas/
│   ├── base.py          # Shared persona + Claude CLI logic
│   ├── product_owner.py # Triage + requirements
│   ├── architect.py     # Design + code review
│   ├── developer.py     # Implementation
│   └── qa.py            # Validation + merge
├── templates/
│   ├── issue_template.md
│   └── pr_template.md
├── Dockerfile
├── docker-compose.yaml
├── config.yaml
└── requirements.txt
```

## Contributing

1. Fork the repo
2. Create a feature branch
3. Submit a PR

## License

MIT
