# Multi-Cluster Observability Operator (MCO)

An ACM operator that deploys hub-side observability infrastructure (Thanos, Grafana, alerting) and installs MCOA on managed clusters. Provides the `MultiClusterObservability` CR as the control surface.

## Quick Reference

### Building and Testing
- `make build` — compile the operator binary
- `make unit-tests` — unit tests (monorepo sub-packages)
- `make lint` — golangci-lint
- `make e2e-tests` — E2E against a live hub cluster
- `make manifests` — regenerate CRDs from API types

### Deployment
- `make deploy` — deploy to hub cluster
- `make undeploy` — remove from hub cluster

### Code Generation
- `make generate` — controller-gen, deepcopy, client-gen
- `make manifests` — regenerate CRD manifests from `//+kubebuilder` markers

## Architecture at a Glance

> For the full architecture index, see [ARCHITECTURE.md](ARCHITECTURE.md).

Monorepo with sub-packages: `operators/`, `proxy/`, `collectors/`, `loaders/`. Watches `MultiClusterObservability` CR, deploys hub components (Thanos, Grafana, Observatorium API) and installs MCOA as an addon.

Key packages:
- `operators/multiclusterobservability/` — main reconciler, status, placement
- `operators/multiclusterobservability/api/v1beta2/` — CR types, deepcopy, validation
- `operators/endpointmetrics/` — spoke-side metrics endpoint operator
- `proxy/` — RBAC-aware Thanos query proxy

### Relationship to MCOA
- MCO installs MCOA via addon-framework (`open-cluster-management.io/addon-framework`)
- MCO owns the `MultiClusterObservability` CR and syncs configuration via `AddOnDeploymentConfig`
- RS feature: MCO defines the API surface, MCOA implements the backend

## Coding Standards

- **Go 1.25+**, monorepo with independent go.mod per sub-package
- **Lint**: golangci-lint with project-specific config
- **Tests**: table-driven + `controller-runtime` fake client + envtest
- **CRDs**: `//+kubebuilder:validation` markers on API types, `controller-gen` for manifests
- **Errors**: sentinel errors + `%w` wrapping

## Documentation

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full documentation index.
