---
name: Claude Task
about: Create a task for the Claude Task Runner
labels: claude, ready
---

```yaml
---
repo: user/target-repo
new_repo: false
priority: medium          # high | medium | low
schedule: once            # once | daily | weekly | monthly
night_only: false         # true = only process in night window
human_review: false       # true = require human sign-off before merge
# depends_on: [12, 15]   # optional: issue numbers that must be done first
# group: feature-name     # optional: group related tasks
---
```

## Task

<!-- Describe what needs to be done. Be specific. -->

## Context

<!-- Provide background: relevant files, architecture, constraints. -->

## Acceptance Criteria

<!-- List specific, testable criteria. Each should be verifiable. -->
- [ ] Criterion 1
- [ ] Criterion 2
- [ ] Criterion 3
