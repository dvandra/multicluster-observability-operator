# MCO Structured Task

## Component
<!-- One of: operators/multiclusterobservability, operators/endpointmetrics, collectors/metrics, proxy, loaders/dashboards, operators/pkg -->

## Architecture
<!-- Legacy / MCOA / Both -->

## Description
<!-- What this task does and why -->

## Files to Modify
<!-- Real verified paths only -->
- `<path>` — <what changes>

## Files to Create
- `<path>` — <purpose>

## Implementation Notes
<!-- Reference real symbols and patterns from the codebase -->
Follow the existing pattern in `<FunctionName>()` at `<file-path>`.
Reuse the `<TypeName>` from `<file-path>`.

## Acceptance Criteria
- [ ] <Testable criterion>
- [ ] <Regression: existing functionality still works>

## Test Requirements
- [ ] Unit test in `<package>_test.go` following existing patterns
- [ ] Integration test with `-tags integration` (if controller change)

## Verification Commands
```bash
make format
make go-lint
make unit-tests
# If integration: make integration-test
```

## Commit Convention
```
feat|fix|test(<component>): <description>

Signed-off-by: Name <email>
```

## Dependencies
- Depends on: <task or none>
