# MCO Rightsizing — Quick Reference

## Metric Names

### Namespace RS (`acm_rs:*`)
- `acm_rs:namespace:cpu_request:5m`, `acm_rs:namespace:cpu_request_quota:5m`
- `acm_rs:namespace:cpu_usage:5m`, `acm_rs:namespace:memory_rss:5m`
- `acm_rs:namespace:memory_working_set:5m`
- `acm_rs:namespace:*:1d` — daily aggregations
- `acm_rs:namespace:*_recommendation` — computed as `max_over_time(usage_5m[1d]) * (pct/100)`
- `acm_rs:cluster:*` — cluster-level aggregations

### Virtualization RS (`acm_rs_vm:*`)
- `acm_rs_vm:namespace:cpu_*`, `acm_rs_vm:namespace:memory_*`
- `acm_rs_vm:cluster:*` — cluster-level
- `kubevirt_vm_running_status_last_transition_timestamp_seconds` — VM status metric

## Key Constants

| Constant | Value |
|----------|-------|
| `RightSizingCapableAnnotation` | `observability.open-cluster-management.io/right-sizing-capable` |
| `RSManagedByLabel` | `observability.open-cluster-management.io/managed-by` |
| `RSManagedByValue` | `analytics-rightsizing` |
| `ADCKeyPlatformNamespaceRightSizing` | `platformNamespaceRightSizing` |
| `ADCKeyPlatformVirtualizationRightSizing` | `platformVirtualizationRightSizing` |
| `DefaultRecommendationPercentage` | `110` |

## Resource Names

| Resource | Namespace | Name |
|----------|-----------|------|
| ConfigMap | `open-cluster-management-observability` | `rs-namespace-config` |
| ConfigMap | `open-cluster-management-observability` | `rs-virt-config` |
| Policy | per-binding namespace | `rs-prom-rules-policy` |
| Policy | per-binding namespace | `rs-virt-prom-rules-policy` |
| PrometheusRule | `openshift-monitoring` (spoke) | `acm-rs-namespace-prometheus-rules` |
| PrometheusRule | `openshift-monitoring` (spoke) | `acm-rs-virt-prometheus-rules` |
| ScrapeConfig | analytics namespace | `platform-metrics-right-sizing` |
| Placement | per-binding namespace | `rs-placement`, `rs-virt-placement` |

## Upcoming Components (from dvandra/ fork)

### Workload-Pod RS (branch: `workload-pod-gpu-rs`)
New sub-package + ADC key for workload/pod-level CPU/memory recommendations.
Pod→workload ownership mapping handles Deployment, StatefulSet, DaemonSet, CronJob, Job, ReplicaSet chains.

### GPU RS (branch: `workload-pod-gpu-rs`)
Source metrics: `accelerator_gpu_utilization`, `DCGM_FI_DEV_FB_USED/FREE`, `accelerator_memory_used_bytes`, `accelerator_power_usage_watts`, `accelerator_temperature_celsius`, `accelerator_sm_clock_hertz`, `accelerator_memory_clock_hertz`
Resources: `kube_pod_container_resource_requests{resource=~"nvidia.com/gpu|amd.com/gpu"}`

### Percentile Profiles (branch: `workload-pod-gpu-rs-profiles`)
Multiple recommendation profiles (P50, P90, P95, P99, max) instead of single percentage.

### Branch Map
| MCO Branch | MCOA Branch | Feature |
|-----------|-------------|---------|
| `rs-virt` | (main) | Virtualization RS |
| `namespace-rs-refactor` | `rs-option-1-placement` | Modularize + remove custom Placement |
| `workload-pod-gpu-rs` | `workload-pod-and-gpu-rs` | Workload + GPU RS |
| `workload-pod-gpu-rs-profiles` | `rs-percentile-profiles-all` | Percentile profiles |
| `right-sizing-delegation` | `decouple-right-sizing-from-metrics-collection` | Delegation hardening |

## Prediction Engine (MCO Side)

### New ADC Keys
| Key | Values | Default |
|-----|--------|---------|
| `platformRightSizingPrediction` | `enabled` / `disabled` | disabled |
| `platformRightSizingPredictionProvider` | `builtin` / `onnx` / `external` / `custom` | `builtin` |
| `platformRightSizingPredictionConfig` | JSON blob | `{}` |

### New Constants (`pkg/util/rightsizing.go`)
```go
ADCKeyPlatformRightSizingPrediction         = "platformRightSizingPrediction"
ADCKeyPlatformRightSizingPredictionProvider  = "platformRightSizingPredictionProvider"
ADCKeyPlatformRightSizingPredictionConfig    = "platformRightSizingPredictionConfig"
```

### New Metrics (for `metrics_allowlist.yaml`)
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

### New Recording Rules (for ScrapeConfig federation)
```
acm_rs:namespace:cpu_forecast_{4h,24h,7d}
acm_rs:namespace:memory_forecast_{4h,24h,7d}
acm_rs:namespace:{cpu,memory}_anomaly_score
acm_rs:namespace:cpu_forecast_{upper,lower}_4h
```

## MCO CR Path

```yaml
spec:
  capabilities:
    platform:
      analytics:
        namespaceRightSizingRecommendation:
          enabled: true
          namespaceBinding: "open-cluster-management-global-set"
        virtualizationRightSizingRecommendation:
          enabled: true
        # Upcoming (from fork branches):
        # workloadPodRightSizingRecommendation:
        #   enabled: true
        # gpuRightSizingRecommendation:
        #   enabled: true
        prediction:
          enabled: true
          provider: "builtin"   # builtin | onnx | external | custom
          builtin:
            trainingInterval: 6h
            historyWindow: 90d
            forecastHorizons: [4h, 24h, 7d]
          # onnx:
          #   modelSource: configmap
          #   modelConfigMap: rs-custom-model
          # external:
          #   endpoint: https://api.openai.com/v1/...
          #   apiKeySecret: rs-prediction-api-key
          #   dataExfiltrationConsent: true
          # custom:
          #   endpoint: https://ml-platform.corp:8443/predict
          #   protocol: grpc
          #   dataExfiltrationConsent: true
```
