# MCO Operator Core

> Main reconciler, CR API types, status management, placement evaluation, and hub component lifecycle. For the right-sizing API surface, see [rightsizing-api.md](rightsizing-api.md). For proxy and RBAC, see [proxy-and-rbac.md](proxy-and-rbac.md).

## Context

The multicluster observability operator is the hub-side controller that reconciles `MultiClusterObservability` (MCO), renders manifests, drives AddonDeploymentConfig (ADC), and coordinates fleet-wide observability. This document maps **verified entry points** and **runtime patterns** so agents and contributors land in the right files without outdated assumptions about layout or reconcile ownership.

## Architecture (structure and control flow)

### Key entry points

Main files verified from the actual repo:

- `operators/multiclusterobservability/main.go` — Manager setup, filtered cache, scheme registration
- `operators/multiclusterobservability/controllers/multiclusterobservability/multiclusterobservability_controller.go` — Main reconciler (`MultiClusterObservabilityReconciler`)
- `operators/multiclusterobservability/api/v1beta2/multiclusterobservability_types.go` — CR types (`kubebuilder:storageversion`)
- `operators/multiclusterobservability/api/shared/multiclusterobservability_shared.go` — Shared structs (custom `Condition`, `ObservabilityAddonSpec`)
- `operators/multiclusterobservability/controllers/status/status_controller.go` — `StatusReconciler` (separate controller)
- `operators/multiclusterobservability/controllers/placementrule/placementrule_controller.go` — Fleet addon controller (watches `ManagedCluster`, not `PlacementRule`)
- `operators/multiclusterobservability/controllers/analytics/analytics_controller.go` — `AnalyticsReconciler`, `syncRightSizingStateToADC`
- `operators/multiclusterobservability/pkg/rendering/renderer.go` — `MCORenderer`, template rendering
- `operators/multiclusterobservability/pkg/rendering/renderer_mcoa.go` — `renderAddonDeploymentConfig`
- `operators/pkg/deploying/deployer.go` — `Deployer.Deploy` with SSA for ADC

### Patterns

**Main reconcile loop (high level):** backup labels → singleton MCO → sidecar controllers → finalizers → MCH gate → pause → storage → rendering → deploy → MCOA path → ingress/routes → certs/observatorium/grafana → legacy cleanup.

**Status:** Status is **not** updated in the main reconciler. `StatusReconciler` owns conditions (`Ready`, `Failed`, `Installing`, `MetricsDisabled`, `MCOADegraded`).

**ADC:** Two paths coexist: the main reconciler renders and applies the full ADC; the analytics reconciler patches right-sizing-related keys—coordinate mentally when debugging “who wrote this field?”

**Module layout:** There is a **single Go module at the repository root** (not an independent `go.mod` per sub-package). Documentation that claims per-package modules is **drift**.

### Gotchas

- **Single Go module** — not per-sub-package as some docs claim.
- **CRD storage version** is `v1beta2`.
- **`PlacementRuleReconciler`** actually watches `ManagedCluster` (misleading name).
- **Placement controller** is started from inside the MCO reconcile loop.
- **ADC competition** between the main reconciler (apply) and the analytics reconciler (patch).
- **Filtered `ManagedCluster` cache** can hide clusters during cleanup.
- **Status vs spec separation:** the main reconciler never updates `Ready`.
- **`collectors/` and `loaders/`** directories are not present in this checkout.

### Dependencies

- controller-runtime, addon-framework, governance-policy-propagator
- observatorium-operator API, prometheus-operator, `openshift/api`
- IBM/controller-filtered-cache

## Links

- [rightsizing-api.md](rightsizing-api.md)
- [proxy-and-rbac.md](proxy-and-rbac.md)
- [ARCHITECTURE.md](../../ARCHITECTURE.md)
