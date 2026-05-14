# Right-Sizing API

> **PARTIAL DRAFT.** The prediction configuration section below is the specification for new code we're building — it's accurate by design. The existing RS schema and ADC sync sections were written from planning context and should be validated against the actual MCO codebase (following the [CHA pattern](https://github.com/openshift/cluster-health-analyzer/pull/108)).

> MCO CR schema for right-sizing capabilities, AddOnDeploymentConfig sync, metrics allowlist, and prediction configuration surface. For the MCOA implementation that reads this config, see `docs/agents/prediction-engine.md` in the MCOA repo. For the MCO operator reconciler, see [mco-operator-core.md](mco-operator-core.md).

## Expected Key Entry Points

- `operators/multiclusterobservability/api/v1beta2/multiclusterobservability_types.go`: CR types — `CapabilitiesSpec` → `PlatformSpec` → `AnalyticsSpec` → `RightSizingSpec`
- `operators/multiclusterobservability/controllers/multiclusterobservability/adc_sync.go`: ADC sync — writes config as customized variables
- `operators/multiclusterobservability/manifests/base/config/metrics_allowlist.yaml`: metrics allowlist for Thanos federation

> Verify these paths against the actual repo before editing.

## Prediction Configuration (Specification)

This section defines what we're building. It's the contract between MCO and MCOA.

### CR Schema Path

```yaml
apiVersion: observability.open-cluster-management.io/v1beta2
kind: MultiClusterObservability
spec:
  capabilities:
    platform:
      analytics:
        rightSizing:
          prediction:
            enabled: true
            provider:
              type: builtin  # builtin | onnx | external | custom
              # For onnx:
              onnxModelConfigMapRef:
                name: my-onnx-model
                namespace: open-cluster-management-observability
              # For external:
              externalAPIKeySecretRef:
                name: prediction-api-key
                namespace: open-cluster-management-observability
              dataExfiltrationConsent: true
              # For custom:
              customEndpointURL: "http://my-model-server.ns.svc:8080/predict"
              dataExfiltrationConsent: true
            config:
              trainingIntervalHours: 6
              historyDays: 30
              safetyMarginPercent: 115
```

### ADC Keys for Prediction

| ADC Key | Value | Source |
|---------|-------|--------|
| `platformRightSizingPrediction` | `"enabled"` / `"disabled"` | `.spec...prediction.enabled` |
| `platformRightSizingPredictionProvider` | `"builtin"` / `"onnx"` / `"external"` / `"custom"` | `.spec...prediction.provider.type` |
| `platformRightSizingPredictionConfig` | JSON blob | `.spec...prediction.config` + provider details |

### Prediction Metrics for Allowlist

These metric names must be added to `metrics_allowlist.yaml` when the prediction engine ships:

```
acm_rs:prediction_forecast_cpu
acm_rs:prediction_forecast_memory
acm_rs:prediction_forecast_gpu
acm_rs:prediction_anomaly_score
acm_rs:prediction_model_accuracy
```

### Key Design Decisions

- **`dataExfiltrationConsent` defaults to false.** External/custom providers are blocked at call time without explicit consent.
- **Secret contents are resolved by MCO, not MCOA.** MCO reads the secret and injects values into the ADC JSON blob. MCOA never reads hub-namespace Secrets directly.
- **Metrics allowlist is manual.** Adding new prediction recording rules in MCOA requires a corresponding MCO allowlist update.

## TODO: Verify Existing RS Schema

To complete this doc, clone the MCO repo and verify:

```
# In the actual MCO repo checkout
# Have an agent read the existing RS types in api/v1beta2/ and produce:
# - Actual struct hierarchy for RightSizingSpec
# - Existing ADC keys for namespace/virtualization RS
# - Current metrics_allowlist.yaml contents
```

## Links

- [mco-operator-core.md](mco-operator-core.md) — reconciler, status, placement
- [ARCHITECTURE.md](../../ARCHITECTURE.md) — documentation index
- MCOA `docs/agents/prediction-engine.md` — MCOA-side implementation
