# MCO Tasks: Prediction Engine API

> Phase 2 output — 4 tasks, runs in parallel with MCOA Batch 1
> Decisions: flat sibling under PlatformAnalyticsSpec, acm_rs:prediction_* naming, independent delegation

---

### Task M1: PredictionSpec API types

- **Component**: operators/multiclusterobservability
- **Architecture**: MCOA
- **Size**: S
- **Depends on**: none

**Files to Modify:**
- `operators/multiclusterobservability/api/v1beta2/multiclusterobservability_types.go` — add PredictionSpec, PredictionProviderSpec, PredictionConfigSpec as sibling field under PlatformAnalyticsSpec

**New Types:**
```go
type PlatformPredictionSpec struct {
    Enabled bool `json:"enabled,omitempty"`
    Provider PredictionProviderSpec `json:"provider,omitempty"`
    Config PredictionConfigSpec `json:"config,omitempty"`
}

type PredictionProviderSpec struct {
    Type string `json:"type,omitempty"` // builtin|onnx|external|custom
    ONNXModelConfigMapRef *corev1.ObjectReference `json:"onnxModelConfigMapRef,omitempty"`
    ExternalAPIKeySecretRef *corev1.ObjectReference `json:"externalAPIKeySecretRef,omitempty"`
    CustomEndpointURL string `json:"customEndpointURL,omitempty"`
    DataExfiltrationConsent bool `json:"dataExfiltrationConsent,omitempty"`
}

type PredictionConfigSpec struct {
    TrainingIntervalHours int `json:"trainingIntervalHours,omitempty"`
    HistoryDays int `json:"historyDays,omitempty"`
    SafetyMarginPercent int `json:"safetyMarginPercent,omitempty"`
}
```

**Implementation Notes:**
- Follow pattern of existing `PlatformRightSizingRecommendationSpec` (flat sibling)
- Add `Prediction PlatformPredictionSpec` field to `PlatformAnalyticsSpec`
- After editing types: `cd operators/multiclusterobservability && make generate manifests`

**Acceptance Criteria:**
- [ ] New types compile and generate deepcopy
- [ ] CRD regenerated with new OpenAPI fields
- [ ] Existing RS fields unchanged
- [ ] `make unit-tests` passes in operators/multiclusterobservability

**Test Requirements:**
- [ ] Webhook tests still pass (no new validation yet)
- [ ] Verify CRD YAML has new fields

**Verification Commands:**
```bash
cd operators/multiclusterobservability
make generate manifests
make test
```

---

### Task M2: ADC key constants + sync

- **Component**: operators/multiclusterobservability
- **Architecture**: MCOA
- **Size**: M
- **Depends on**: Task M1

**Files to Modify:**
- `operators/multiclusterobservability/pkg/util/rightsizing.go` — add 3 new ADC key constants
- `operators/multiclusterobservability/controllers/analytics/analytics_controller.go` — extend syncRightSizingStateToADC with prediction keys; add syncPredictionStateToADC or inline; resolve Secret for API key; build JSON config blob

**New Constants:**
```go
ADCKeyPlatformRightSizingPrediction         = "platformRightSizingPrediction"
ADCKeyPlatformRightSizingPredictionProvider = "platformRightSizingPredictionProvider"
ADCKeyPlatformRightSizingPredictionConfig   = "platformRightSizingPredictionConfig"
```

**Implementation Notes:**
- Follow existing pattern in syncRightSizingStateToADC (lines 291-374 of analytics_controller.go)
- Prediction sync is INDEPENDENT of delegatingToMCOA — always syncs prediction state
- PredictionConfig JSON blob: marshal PredictionConfigSpec + resolved provider details
- Secret for externalAPIKeySecretRef: read from hub namespace, embed in JSON (MCOA doesn't read Secrets)

**Acceptance Criteria:**
- [ ] Three new ADC keys synced to AddOnDeploymentConfig
- [ ] Prediction sync works regardless of delegatingToMCOA value
- [ ] Secret content resolved and embedded in config JSON
- [ ] Missing Secret returns error (doesn't silently skip)

**Test Requirements:**
- [ ] analytics_controller_test.go: extend TestSyncRightSizingStateToADC for prediction keys
- [ ] Test prediction enabled/disabled independently of RS
- [ ] Test JSON blob construction with mock Secret

---

### Task M3: MCOA renderer + ADC variables

- **Component**: operators/multiclusterobservability
- **Architecture**: MCOA
- **Size**: S
- **Depends on**: Task M1 (types), Task M2 (constants)

**Files to Modify:**
- `operators/multiclusterobservability/pkg/rendering/renderer_mcoa.go` — append 3 prediction customized variables in renderAddonDeploymentConfig (follow existing appendCustomVar pattern at ~line 266-278)

**Implementation Notes:**
- Follow exact pattern of existing RS vars: appendCustomVar for each key
- Values come from MCO CR spec.capabilities.platform.analytics.prediction
- This is the SSA/deploy path; analytics controller patches later

**Acceptance Criteria:**
- [ ] ADC rendered with prediction variables when prediction enabled
- [ ] ADC rendered without prediction variables when prediction not set
- [ ] Existing RS variables unchanged

**Test Requirements:**
- [ ] renderer_mcoa_test.go: bump expected variable count; assert prediction variables present
- [ ] Test with prediction disabled: variable count matches pre-change

---

### Task M4: Metrics allowlist + scrape-config

- **Component**: operators/multiclusterobservability
- **Architecture**: MCOA
- **Size**: S
- **Depends on**: none (independent, but metric names must match MCOA)

**Files to Modify:**
- `operators/multiclusterobservability/manifests/base/config/metrics_allowlist.yaml` — add prediction metric names under names list
- `operators/multiclusterobservability/manifests/base/grafana/analytics/scrape-config.yaml` — add match[] entries for prediction recording rules

**New Metric Names (acm_rs:prediction_* style):**
```yaml
# metrics_allowlist.yaml additions
- acm_rs:prediction_forecast_cpu
- acm_rs:prediction_forecast_memory
- acm_rs:prediction_anomaly_score
- acm_rs:prediction_model_accuracy
- acm_rs:prediction_ensemble_weight
```

```yaml
# scrape-config.yaml match[] additions
- '{__name__=~"acm_rs:prediction_.*"}'
```

**Acceptance Criteria:**
- [ ] New metric names in allowlist YAML
- [ ] Scrape-config match[] includes prediction pattern
- [ ] Existing RS metrics unchanged
- [ ] YAML is valid (no syntax errors)

**Test Requirements:**
- [ ] YAML lint passes
- [ ] Optional: E2E test verifying metrics appear after install

---

## Summary

| Task | Description | Size | Depends On |
|------|------------|------|-----------|
| M1 | PredictionSpec API types | S | none |
| M2 | ADC key constants + sync | M | M1 |
| M3 | MCOA renderer + ADC variables | S | M1, M2 |
| M4 | Metrics allowlist + scrape-config | S | none |

**M1 and M4 can run in parallel.** M2 depends on M1. M3 depends on M1+M2.
