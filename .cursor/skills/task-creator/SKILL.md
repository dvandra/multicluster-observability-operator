---
name: mco-task-creator
description: >-
  Convert an approved MCO impact map into structured development tasks.
  Use after impact map review for multicluster-observability-operator.
---
# MCO Structured Task Creator

Convert approved MCO impact maps into implementation-ready tasks.

## MCO-Specific Rules

1. **One component per task** — separate tasks for MCO operator, endpoint operator, proxy, etc.
2. **Architecture tagging** — mark each task as Legacy, MCOA, or Both
3. **Backward compatibility** — if modifying `operators/multiclusterobservability`, note compat requirements
4. **DCO sign-off** — remind in every task that commits need `Signed-off-by`
5. **Test requirements** — unit tests are mandatory for all new logic

## Task Template Additions for MCO

Each task must include:
- **Component**: which of the 5 MCO components this targets
- **Architecture**: Legacy / MCOA / Both
- **Make targets**: which `make` targets verify this task (e.g., `make unit-tests`, `make go-lint`)

## Workflow

1. Read the approved impact map from `docs/impact-maps/`
2. Read `templates/task-template.md`
3. For each task, verify file paths still exist
4. Find the specific Go symbols (functions, types, interfaces) referenced
5. Order by dependency — shared `operators/pkg/` changes before component changes
6. Save tasks to `docs/tasks/<feature-slug>/task-<N>.md`
