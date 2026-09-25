---
name: mco-tester
description: >-
  Write comprehensive tests for MCO implementations. Covers unit tests (mandatory),
  integration tests (controller interactions), and E2E patterns.
---
# MCO Tester

Write tests for the multicluster-observability-operator following existing patterns.

## Test Framework

- **Unit tests**: standard `go test` with `-race` + `testify` (assert/require)
- **Integration tests**: `-tags integration` + envtest
- **E2E tests**: Ginkgo v2 (in `tests/pkg/tests/`)

## Test Organization

| Layer | Location | Make Target | When to Write |
|-------|----------|-------------|---------------|
| Unit | `*_test.go` next to source | `make unit-tests` | Always (mandatory) |
| Integration | `*_test.go` with `integration` build tag | `make integration-test` | Controller changes |
| E2E | `tests/pkg/tests/` | `make e2e-tests` (CI only) | Major features |

## Unit Test Patterns for MCO

1. **Find existing tests** in the same package — follow their patterns exactly
2. **Controller tests**: use `controller-runtime` fake client
3. **Table-driven tests**: preferred for functions with multiple input combinations
4. **Test file naming**: `<source_file>_test.go` in the same directory

## Test Discovery Workflow

1. Read the task's "Test Requirements"
2. Find existing `*_test.go` files in the affected packages
3. Understand the test helper patterns used (fake clients, fixtures)
4. Write tests covering:
   - Happy path
   - Error conditions
   - Edge cases
   - Backward compatibility (especially for API changes)
5. Run `make unit-tests` and verify all pass
6. For integration tests: `make integration-test`

## Coverage Map

Report which acceptance criteria have test coverage:

```
| Criterion | Unit Test | Integration | E2E |
|-----------|-----------|-------------|-----|
| ...       | file:func | file:func   | —   |
```
