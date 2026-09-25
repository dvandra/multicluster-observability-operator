---
name: mco-ci-fixer
description: >-
  Diagnose and fix CI failures on MCO PRs. Handles lint, bundle, integration test,
  and Konflux pipeline failures. Use when CI is red on an MCO PR.
---
# MCO CI Fixer

Fix CI failures on multicluster-observability-operator PRs.

## MCO CI Pipeline

GitHub Actions runs these checks:
1. **lint.yaml**: `make lint` then `make bundle` + git diff check
2. **integration_tests.yaml**: `make deps` → `make build` → envtest → `make integration-test`

Konflux/Tekton runs container image builds per component.

## Common MCO CI Failures

| Failure | Diagnosis | Fix |
|---------|-----------|-----|
| `make lint` fails | Format, deps, copyright, or golangci-lint | Run `make format`, `make deps`, add copyright headers |
| `make bundle` diff | Generated bundle doesn't match committed | Run `make bundle` and commit the diff |
| Copyright check | Missing boilerplate | Add header from `hack/boilerplate.go.txt` |
| faillint | `fmt.Print*` used in non-test code | Replace with structured logging |
| Containerfile labels | Missing/wrong name or cpe labels | Fix labels, verify with `make verify-containerfile-labels` |
| Integration test fail | Controller logic or envtest setup issue | Read test output, fix code or test |
| vendor mismatch | go.mod changed but vendor not updated | Run `make deps` (runs tidy + vendor) |

## Fix Workflow

1. Read CI failure logs (use `gh` CLI)
2. Categorize the failure (see table above)
3. Apply the smallest fix
4. Run the relevant `make` target locally to verify
5. Commit with DCO sign-off: `git commit -s -m "fix(ci): description"`
6. Push and re-check
7. Loop until green (max 5 attempts)

## Critical Rules

- NEVER disable a failing test
- NEVER skip copyright or lint checks
- Always run `make format` after any code change
- If `make lint` fails due to uncommitted changes, use `make go-lint` to isolate Go lint issues
- Bundle diff: always re-run `make bundle` rather than manually editing generated files
