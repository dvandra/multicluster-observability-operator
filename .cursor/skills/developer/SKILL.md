---
name: mco-developer
description: >-
  Implement a structured task for MCO following approved plan and Go conventions.
  Use when the user says "implement", "develop", "code" for a MCO task.
---
# MCO Developer

Implement structured tasks for the multicluster-observability-operator.

## Before Writing Code

1. Read the task spec from `docs/tasks/`
2. Read AGENTS.md sections 1-3 for architectural constraints
3. Read all files listed in the task's "Files to Modify"
4. Read the reference patterns in "Implementation Notes"

## MCO Go Coding Standards

From AGENTS.md — enforce strictly:
- **Go 1.25+**: Use `iter`, range-over-func, `maps.All`, `slices.Values`
- **Std lib first**: Favor standard library over new dependencies
- **Error wrapping**: `fmt.Errorf("context: %w", err)` — handle once (log OR return)
- **Structured logging**: `log.Info("msg", "key", value)` — log all state changes
- **K8s idioms**: Idempotent reconcilers, Status subresource updates, `client.Reader` for cached reads
- **No fmt.Print**: faillint bans `fmt.Print*` outside tests in operator/collector/proxy/loader
- **Comments**: "Why" over "What" — only for non-obvious logic

## Implementation Workflow

1. Create branch: `agent/<ticket>-<description>`
2. Implement changes following existing patterns exactly
3. Write unit tests for all new/modified logic
4. Run `make format`
5. Run `make go-lint` (fast check)
6. Run `make unit-tests` for the affected component
7. Self-review against acceptance criteria
8. Commit with DCO: `git commit -s -m "feat(component): description"`
9. Open PR: `[TICKET] description`

## Post-Implementation Checks

- [ ] `make format` passes
- [ ] `make go-lint` passes
- [ ] `make unit-tests` passes
- [ ] All acceptance criteria met
- [ ] No `vendor/` changes unless go.mod was modified (then `make deps`)
- [ ] Containerfile labels valid if Dockerfiles touched (`make verify-containerfile-labels`)
- [ ] Copyright headers present on new files
- [ ] DCO sign-off on all commits
