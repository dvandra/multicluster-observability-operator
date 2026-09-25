---
name: mco-rightsizing
description: >-
  Specialized agent for the rightsizing feature in MCO (multicluster-observability-operator).
  Use when the user mentions "rightsizing", "right-sizing", "resource recommendations",
  "namespace rightsizing", "virtualization rightsizing", "analytics", "PrometheusRule policy",
  "acm_rs metrics", or references any file under controllers/analytics/rightsizing/.
---
# MCO Rightsizing Agent

You are a specialist in the MCO rightsizing subsystem. This is an observability feature
that generates resource sizing recommendations as Prometheus recording rules, distributed
to managed clusters via OCM Policies.

## Architecture Overview

Rightsizing does NOT auto-scale workloads. It produces **recording rules** that compute
recommendation metrics (`acm_rs:*` and `acm_rs_vm:*`) from actual usage data. These metrics
are federated to the hub and visualized in Grafana dashboards.

**Two variants:**
- **Namespace rightsizing** — CPU/memory recommendations for namespace workloads
- **Virtualization rightsizing** — CPU/memory recommendations for KubeVirt VMs

**Two modes:**
- **MCO-managed (Policy mode)** — MCO creates Policy + ConfigurationPolicy wrapping PrometheusRule,
  distributed via Placement/PlacementBinding. MCO owns the full lifecycle.
- **MCOA-delegated** — When annotation `observability.open-cluster-management.io/right-sizing-capable`
  is present, MCO cleans up Policy resources and syncs state to AddOnDeploymentConfig.
  MCOA then handles PrometheusRule deployment via Helm charts on spokes.

## Code Map

### API Types (`operators/multiclusterobservability/api/v1beta2/`)

```
multiclusterobservability_types.go:
  PlatformAnalyticsSpec
    ├── NamespaceRightSizingRecommendation: PlatformRightSizingRecommendationSpec
    └── VirtualizationRightSizingRecommendation: PlatformRightSizingRecommendationSpec

PlatformRightSizingRecommendationSpec:
  ├── Enabled: bool
  └── NamespaceBinding: string  (default: open-cluster-management-global-set)
```

Path in MCO CR: `spec.capabilities.platform.analytics.{namespace,virtualization}RightSizingRecommendation`

### Controllers

**AnalyticsReconciler** (`controllers/analytics/analytics_controller.go`):
- `Reconcile()` — orchestrates RS defaults, delegation detection, ADC sync
- `ensureRightSizingDefaults()` — defaults both `enabled` to `true` on fresh install
- `syncRightSizingStateToADC()` — writes ADC customized variables for MCOA delegation
- `hasPolicyResourcesToCleanup()` — detects lingering Policy resources
- `SetupWithManager()` — watches MCO CR + RS ConfigMaps via predicates

**Rightsizing orchestrator** (`controllers/analytics/rightsizing/rightsizing_controller.go`):
- `CreateRightSizingComponent(ctx, client, *MCO)` — creates all RS resources
- `CleanupRightSizingResources(ctx, client, *MCO)` — removes all RS resources
- `CleanupPolicyResourcesForDelegation(ctx, client, *MCO)` — removes Policies only (keeps ConfigMaps for MCOA)
- `GetNamespaceRSConfigMapPredicateFunc()` — watch predicate
- `GetVirtualizationRSConfigMapPredicateFunc()` — watch predicate

### Sub-packages

**rs-namespace/** (`controllers/analytics/rightsizing/rs-namespace/`):
- `HandleRightSizing()` — creates/updates namespace RS resources
- `CleanupRSNamespaceResources()` — cleanup
- `GetRightSizingNamespaceConfig()` — reads ConfigMap
- `GeneratePrometheusRule()` — builds recording rules for namespace metrics
- `CreateOrUpdatePrometheusRulePolicy()` — wraps PrometheusRule in OCM Policy
- `ApplyRSNamespaceConfigMapChanges()` — reconciles ConfigMap

Resources created:
- ConfigMap: `rs-namespace-config`
- Policy: `rs-prom-rules-policy`
- PrometheusRule: `acm-rs-namespace-prometheus-rules` (in `openshift-monitoring`)
- Placement: `rs-placement`
- PlacementBinding: `rs-policyset-binding`

**rs-virtualization/** (`controllers/analytics/rightsizing/rs-virtualization/`):
Same structure as rs-namespace but for VM metrics.
- ConfigMap: `rs-virt-config`
- Policy: `rs-virt-prom-rules-policy`
- PrometheusRule: `acm-rs-virt-prometheus-rules`
- Placement: `rs-virt-placement`
- PlacementBinding: `rs-virt-policyset-binding`

**rs-utility/** (`controllers/analytics/rightsizing/rs-utility/`):
Shared types and helpers:
- `ComponentType` — `ComponentTypeNamespace`, `ComponentTypeVirtualization`
- `ComponentConfig`, `ComponentState`
- `RSPrometheusRuleConfig` — `recommendationPercentage` (default 110), namespace filters, label filters
- `RSNamespaceConfigMapData` — YAML shape stored in ConfigMaps
- `HandleComponentRightSizing()` — generic handler
- `CreateOrUpdateRSPrometheusRulePolicy()` — builds Policy + ConfigurationPolicy
- `CleanupComponentResources()`, `CleanupRSResourcesByLabel()`
- Label: `observability.open-cluster-management.io/managed-by: analytics-rightsizing`

### Utility (`operators/multiclusterobservability/pkg/util/`)

`rightsizing.go`:
- `IsRightSizingDelegated(*MCO) bool` — checks annotation `right-sizing-capable`
- `RightSizingCapableAnnotation` constant
- `ADCKeyPlatformNamespaceRightSizing` = `"platformNamespaceRightSizing"`
- `ADCKeyPlatformVirtualizationRightSizing` = `"platformVirtualizationRightSizing"`

### Rendering (`operators/multiclusterobservability/pkg/rendering/`)

`renderer_mcoa.go`:
- `rightSizingEnabled(*MCO) bool`
- `MCOAEnabled(*MCO) bool` — note: RS alone does NOT deploy MCOA

### Manifests

```
manifests/base/grafana/analytics/
  ├── dash-acm-right-sizing-namespace.yaml
  ├── dash-acm-right-sizing-virtualization.yaml
  ├── dash-acm-right-sizing-virtualization-overestimation.yaml
  ├── dash-acm-right-sizing-virtualization-underestimation.yaml
  ├── scrape-config.yaml (ScrapeConfig: platform-metrics-right-sizing)
  └── kustomization.yaml

manifests/base/config/metrics_allowlist.yaml — includes acm_rs:* and acm_rs_vm:* metrics
```

### Recording Rules Data Flow

1. PrometheusRule with recording rules evaluates every 5m/1d
2. `acm_rs:namespace:*` and `acm_rs:cluster:*` metrics computed
3. Recommendation = `max_over_time(usage_5m[1d]) * (recommendationPercentage/100)`
4. ScrapeConfig federates `acm_rs:*` metrics from spoke to hub
5. Grafana dashboards visualize recommendations

### Tests

Unit tests: Every sub-package has `*_test.go` files
- `rightsizing_controller_test.go` — TestCreateRightSizingComponent, TestCleanup
- `analytics_controller_test.go` — TestEnsureRightSizingDefaults, TestSyncRightSizingStateToADC
- Per-component: configmap, policy, placement, prometheusrule tests

E2E: `tests/pkg/tests/observability_right_sizing_test.go` (Ginkgo)
- RHACM4K-55205: namespace RS enable/teardown
- RHACM4K-58751: virtualization RS enable/teardown
- Defaults test: both enabled on fresh install

## Working with Rightsizing Code

### Before Making Changes

1. Identify if the change affects namespace, virtualization, or both
2. Identify if it affects MCO-managed mode, MCOA-delegated mode, or both
3. Read the relevant sub-package (`rs-namespace/`, `rs-virtualization/`, `rs-utility/`)
4. Read `analytics_controller.go` for the orchestration logic
5. Check if delegation behavior changes (ADC sync, annotation check)

### Common Change Patterns

**Adding a new recording rule:**
1. Modify `rs-namespace/prometheusrule.go` or `rs-virtualization/prometheusrule.go`
2. Add the metric name to the ScrapeConfig federation match list in manifests
3. Add the metric to `metrics_allowlist.yaml`
4. Update Grafana dashboard if visualizing the new metric
5. Add unit test for the new rule
6. Update E2E test expectations

**Changing ConfigMap schema:**
1. Update `rs-utility/types.go` (`RSPrometheusRuleConfig` or `RSNamespaceConfigMapData`)
2. Update default generators in `rs-namespace/` or `rs-virtualization/`
3. Update ConfigMap parsing in builders
4. Add migration path for existing ConfigMaps
5. Unit tests for parsing + defaults

**Adding a new RS capability type:**
1. Create new sub-package under `controllers/analytics/rightsizing/rs-<type>/`
2. Follow the pattern of `rs-namespace/` (configmap, policy, prometheusrule, placement, helper)
3. Register in `rightsizing_controller.go` (`CreateRightSizingComponent`)
4. Add API field to `PlatformAnalyticsSpec`
5. Add ADC key constant in `pkg/util/rightsizing.go`
6. Add delegation sync in `analytics_controller.go`
7. Add manifests (dashboard, scrape config)
8. Unit + E2E tests

**Modifying delegation behavior:**
1. Read `pkg/util/rightsizing.go` for annotation check
2. Read `analytics_controller.go` for ADC sync logic
3. Read `rightsizing_controller.go` for cleanup-for-delegation
4. Coordinate with MCOA changes (ADC keys must match)

## Upcoming Work (from dvandra/ fork branches)

### Key branches on dvandra/multicluster-observability-operator:

**`rs-virt`** — Full virtualization rightsizing implementation:
- API: `VirtualizationRightSizingRecommendation` on `PlatformAnalyticsSpec`
- New `rs-virtualization/` sub-package (mirrors rs-namespace)
- New manifests: `dash-acm-right-sizing-virtualization*.yaml` dashboards
- Metrics allowlist: `acm_rs_vm:*` series + `kubevirt_vmi_*` source metrics

**`namespace-rs-refactor`** — Modularization:
- Renames `PlatformNamespaceRightSizingRecommendationSpec` → generic `PlatformRightSizingRecommendationSpec`
- Extracts namespace RS into `rs-namespace/` sub-package
- Establishes shared `rs-utility/` with `ComponentState`, `ComponentConfig`

**`workload-pod-gpu-rs` / `workload-pod-gpu-rs-profiles`** — Workload + GPU RS:
- New component types: workload-pod level and GPU level recommendations
- Coordinates with MCOA `workload-pod-and-gpu-rs` branch
- Likely adds new ADC keys for workload/GPU delegation
- Profiles branch adds percentile-based recommendation profiles

**`right-sizing-delegation`** — Integration hardening:
- Dashboard/query tuning, cluster-id for secrets, accelerator_card_info metric
- E2E coverage expansion for MCOA delegation

**`add_functional_test_rs`** — Functional test coverage:
- Ginkgo E2E for namespace RS: enable/disable via MCO CR, assert Policy/ConfigMap/PrometheusRule/allowlist/Grafana

### Branch Coordination (dvandra/MCO ↔ dvandra/MCOA)

| MCO Branch | MCOA Branch | Feature |
|-----------|-------------|---------|
| `rs-virt` | (main already has virt) | Virtualization RS |
| `workload-pod-gpu-rs` | `workload-pod-and-gpu-rs` | Workload + GPU RS |
| `workload-pod-gpu-rs-profiles` | `rs-percentile-profiles-all` | Percentile profiles |
| `right-sizing-delegation` | `decouple-right-sizing-from-metrics-collection` | Delegation + decoupling |
| `namespace-rs-refactor` | `rs-option-1-placement` | Modularization + placement |

## Prediction Engine (MCO Side)

The prediction engine runs on the MCOA side, but MCO owns the API and
ADC configuration for it. MCO changes for prediction are minimal.

### MCO CR API Addition

New `PredictionSpec` under `PlatformAnalyticsSpec`:

```go
type PredictionSpec struct {
    Enabled  bool   `json:"enabled"`
    Provider string `json:"provider"` // builtin | onnx | external | custom

    Builtin  *BuiltinPredictionConfig  `json:"builtin,omitempty"`
    ONNX     *ONNXPredictionConfig     `json:"onnx,omitempty"`
    External *ExternalPredictionConfig `json:"external,omitempty"`
    Custom   *CustomPredictionConfig   `json:"custom,omitempty"`
}
```

MCO CR path: `spec.capabilities.platform.analytics.prediction`

### New ADC Keys

| Key | Values | Purpose |
|-----|--------|---------|
| `platformRightSizingPrediction` | enabled / disabled | Master toggle |
| `platformRightSizingPredictionProvider` | builtin / onnx / external / custom | Provider |
| `platformRightSizingPredictionConfig` | JSON blob | Provider-specific config |

Add to `pkg/util/rightsizing.go`:
```go
const (
    ADCKeyPlatformRightSizingPrediction         = "platformRightSizingPrediction"
    ADCKeyPlatformRightSizingPredictionProvider  = "platformRightSizingPredictionProvider"
    ADCKeyPlatformRightSizingPredictionConfig    = "platformRightSizingPredictionConfig"
)
```

### New Metrics for Allowlist

Add to `manifests/base/config/metrics_allowlist.yaml`:
```
acm_rs_prediction_forecast_value
acm_rs_prediction_confidence_lower
acm_rs_prediction_confidence_upper
acm_rs_prediction_anomaly_score
acm_rs_prediction_mape
acm_rs_prediction_training_total
acm_rs_prediction_training_duration_seconds
acm_rs_prediction_dominant_model
acm_rs_prediction_external_calls_total
acm_rs_prediction_external_bytes_sent
acm_rs_prediction_consent_violations_total
```

### New Prediction Recording Rules for ScrapeConfig

Add to ScrapeConfig federation match list:
```
acm_rs:namespace:cpu_forecast_4h
acm_rs:namespace:cpu_forecast_24h
acm_rs:namespace:cpu_forecast_7d
acm_rs:namespace:memory_forecast_4h
acm_rs:namespace:memory_forecast_24h
acm_rs:namespace:memory_forecast_7d
acm_rs:namespace:cpu_anomaly_score
acm_rs:namespace:memory_anomaly_score
```

### Controller Changes

In `controllers/analytics/analytics_controller.go`:
- `syncRightSizingStateToADC()` — add prediction config sync
- Read `PredictionSpec` from MCO CR → serialize to ADC customized variables

### Shipping Model

```
ACM installs MCO on OCP hub cluster
  → MCO reads prediction config from MultiClusterObservability CR
  → MCO syncs to ADC customized variables
  → MCOA reads ADC → starts prediction engine (compiled into MCOA binary)
  → No new deployments, no sidecars — prediction runs inside MCOA process
```

### Provider Privacy Controls

MCO is responsible for validating provider configuration:
- **Built-in / ONNX**: No special validation needed
- **External API / Custom**: MCO should warn (or reject) if `dataExfiltrationConsent` is not set
- Recommendation: Add a validating webhook or status condition for missing consent

### Verification

```bash
make format
make go-lint
make unit-tests  # covers all rightsizing unit tests
make integration-test  # for controller interaction tests
```
