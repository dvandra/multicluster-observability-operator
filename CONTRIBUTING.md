# Contributing

## Development Setup

1. Install Go 1.25+
2. Clone the repo
3. Build: `make build`
4. Test: `make unit-tests`
5. Lint: `make lint`

## Running Tests

```bash
make unit-tests              # unit tests
make e2e-tests               # E2E (requires oc login + hub cluster)
make lint                    # linting
```

## Submitting Changes

1. Fork the repo and create a branch from `main`.
2. API changes go in `operators/multiclusterobservability/api/v1beta2/`.
3. Run `make manifests` after API type changes to regenerate CRDs.
4. Run `make generate` after adding/changing controller interfaces.
5. Run `make lint` before submitting PRs.
6. Open a pull request with a clear description of what changed and why.

## Code Style

- Go 1.25+ idioms; monorepo with independent go.mod per sub-package
- Import groups: stdlib, external, internal
- Error handling: wrap with `%w`, handle once
- CRD markers: `//+kubebuilder:validation` on API types

## Project Documentation

See [docs/agents/](docs/agents/) for detailed architecture and subsystem documentation.
