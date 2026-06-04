# Right-sizing recommendations with Perses dashboards: A developer preview

**Authors:** [Darshan Vandra](https://developers.redhat.com/author/darshan-vandra), [Raj Zalavadia](https://developers.redhat.com/author/raj-zalavadia)

**Related products:** [Red Hat Advanced Cluster Management for Kubernetes](https://developers.redhat.com/products/advanced-cluster-management-kubernetes), [Red Hat OpenShift Virtualization](https://www.redhat.com/en/technologies/cloud-computing/openshift/virtualization)

---

## Table of contents

- [Introduction](#introduction)
- [What's new in this developer preview](#whats-new-in-this-developer-preview)
- [Architecture: From MCO to MCOA](#architecture-from-mco-to-mcoa)
- [Perses dashboards for right-sizing](#perses-dashboards-for-right-sizing)
- [Getting started](#getting-started)
- [What's next](#whats-next)

---

## Introduction

Since the [general availability of right-sizing recommendations](https://developers.redhat.com/articles/2026/03/17/advanced-cluster-management-216-right-sizing-recommendation-ga) in Red Hat Advanced Cluster Management for Kubernetes 2.16, platform engineers have had access to data-driven CPU and memory optimization insights across their multicluster environments. The integrated Grafana dashboards provide visibility into resource allocation efficiency at the cluster, namespace, and virtual machine levels.

In that GA release, we shared our intent to extend right-sizing recommendation dashboard support to [Perses](https://perses.dev/)—the CNCF sandbox project for cloud-native observability dashboards. Today, we are excited to announce the **developer preview** of right-sizing recommendations with Perses dashboards, delivered through the Multicluster Observability Addon (MCOA) as part of Red Hat Advanced Cluster Management 2.17.

This developer preview brings together two significant advancements:

1. **Perses-native dashboards** for namespace and virtualization right-sizing, replacing the legacy Grafana-based visualization with a Kubernetes-native, RBAC-aware dashboard experience.
2. **Right-sizing delegation to MCOA**, migrating the recommendation engine from the MCO's Policy-based delivery to a modern ManifestWork-based approach through the addon framework.

## What's new in this developer preview

### Perses: The next generation of observability dashboards

[Red Hat build of Perses](https://developers.redhat.com/articles/2026/04/02/red-hat-build-perses-cluster-observability-operator), introduced as a technology preview in the cluster observability operator 1.4, brings a modern, Kubernetes-native dashboarding experience to OpenShift. Unlike traditional Grafana deployments, Perses offers:

- **Native Kubernetes RBAC**: Dashboard access is governed by standard Kubernetes role-based access control. Users see only the dashboards they are authorized to access.
- **Dashboard-as-Code**: Dashboards are defined as `PersesDashboard` custom resources, enabling GitOps workflows, version control, and reproducible deployments.
- **Integrated OpenShift console experience**: Dashboards appear directly in the OpenShift console under Observe → Dashboards (Perses), eliminating the need to manage separate Grafana instances.
- **Simplified migration**: Built-in Grafana import tools allow seamless migration of existing dashboard configurations.

### Right-sizing with Perses: Namespace and virtualization

This developer preview includes dedicated Perses dashboards for both right-sizing recommendation variants:

**Namespace right-sizing dashboard** provides:

- Cluster-level CPU and memory overestimation and underestimation totals
- Per-namespace CPU and memory usage, request, recommendation, and utilization percentage
- Sortable tables with conditional formatting to highlight over-provisioned (red) and under-provisioned (yellow) namespaces
- Time aggregation filtering (1-day, 7-day, 15-day, 30-day windows)
- Cluster and namespace dropdown filters

**Virtualization right-sizing dashboard** provides:

- Total CPU and memory overestimation and underestimation across all VMs in a cluster
- Per-VM utilization tables showing CPU and memory over/underestimation
- Links to detailed per-VM time-series charts for historical trend analysis
- Filtering by cluster, namespace, and time aggregation period

Both dashboards are powered by the same `acm_rs:*` and `acm_rs_vm:*` Prometheus recording rules that drive the existing Grafana dashboards, ensuring consistency in recommendation logic while upgrading the visualization layer.

## Architecture: From MCO to MCOA

A key architectural change in this developer preview is the delegation of right-sizing recommendation deployment from the Multicluster Observability Operator (MCO) to the Multicluster Observability Addon (MCOA).

### Previous architecture (MCO-managed)

In the GA release (ACM 2.16), MCO managed the full right-sizing lifecycle directly:

```
MCO reads MultiClusterObservability CR
  → Creates Policy + ConfigurationPolicy wrapping PrometheusRule
  → Distributes via Placement/PlacementBinding to managed clusters
  → Recording rules evaluate on spoke Prometheus
  → Metrics federated to hub via ScrapeConfig
  → Grafana dashboards visualize recommendations
```

### New architecture (MCOA-delegated)

With this developer preview, MCO delegates right-sizing to MCOA when the delegation annotation is present:

```
MCO reads MultiClusterObservability CR
  → Detects delegation annotation (right-sizing-capable)
  → Syncs RS state to AddOnDeploymentConfig (ADC)
  → Cleans up legacy Policy resources

MCOA reads ADC keys (platformNamespaceRightSizing=enabled)
  → Evaluates in-memory Placement predicates for cluster selection
  → Generates PrometheusRules + ScrapeConfig per feature
  → Helm chart renders into ManifestWork
  → Addon framework deploys to spoke clusters
  → Perses dashboards deployed on hub for visualization
```

### Benefits of MCOA delegation

| Aspect | MCO (Policy-based) | MCOA (ManifestWork-based) |
|--------|-------------------|--------------------------|
| Delivery mechanism | OCM Policy + ConfigurationPolicy | Addon framework ManifestWork |
| Cluster targeting | Placement + PlacementBinding | In-memory predicate evaluation |
| Configuration | ConfigMaps managed by MCO | ConfigMaps managed by MCOA |
| Dashboard technology | Grafana (ConfigMap-based) | Perses (CRD-based, RBAC-aware) |
| Lifecycle management | MCO reconciler | MCOA addon controller |

Key advantages of the MCOA approach:

1. **Simplified resource model**: Eliminates the need for Policy, ConfigurationPolicy, and PlacementBinding resources.
2. **Addon-native lifecycle**: Right-sizing resources follow the same lifecycle as other MCOA-managed components.
3. **In-memory placement**: Cluster selection is evaluated in-memory rather than through separate Placement API resources, reducing cluster overhead.
4. **Perses-native dashboards**: Dashboard definitions are deployed as `PersesDashboard` CRDs, benefiting from Kubernetes-native RBAC and GitOps compatibility.

## Perses dashboards for right-sizing

### Namespace right-sizing dashboard

The namespace right-sizing Perses dashboard provides a comprehensive view of CPU and memory allocation efficiency across namespaces in your managed clusters.

**Dashboard sections:**

1. **Cluster overview panel**: Displays aggregate CPU/memory recommendation versus request at the cluster level, with overestimation and underestimation totals.

2. **Namespace detail table**: A sortable, filterable table showing per-namespace metrics:
   - CPU/Memory utilization (percentage of request actually used)
   - CPU/Memory usage (actual consumption)
   - CPU/Memory request (configured allocation)
   - CPU/Memory recommendation (computed optimal value)
   - CPU/Memory over/underestimation (delta between request and recommendation)

3. **Time-series trends**: Visual representation of utilization over the selected aggregation period.

**Recording rules powering the dashboard:**

- `acm_rs:namespace:cpu_request` — CPU request per namespace
- `acm_rs:namespace:cpu_usage_max_5m` — Max CPU usage over 5-minute windows
- `acm_rs:namespace:cpu_recommendation_1d` — Daily CPU recommendation
- `acm_rs:namespace:memory_request` — Memory request per namespace
- `acm_rs:namespace:memory_usage_max_5m` — Max memory usage over 5-minute windows
- `acm_rs:namespace:memory_recommendation_1d` — Daily memory recommendation
- `acm_rs:cluster:cpu_*` / `acm_rs:cluster:memory_*` — Cluster-level aggregates

### Virtualization right-sizing dashboard

The virtualization right-sizing Perses dashboard extends resource optimization visibility to OpenShift Virtualization workloads.

**Dashboard sections:**

1. **VM overestimation/underestimation overview**: Aggregated CPU and memory deltas across all virtual machines in the selected cluster.

2. **Per-VM utilization tables**: Four detailed tables for CPU overestimation, CPU underestimation, memory overestimation, and memory underestimation, each showing:
   - VM name and namespace
   - Current utilization percentage
   - Usage, request, and recommendation values
   - Over/underestimation amount with color-coded indicators

3. **VM detail view**: Clicking a VM name navigates to a detailed time-series view with CPU and memory utilization trends over time.

**Recording rules powering the dashboard:**

- `acm_rs_vm:pod:cpu_usage_max_5m` — Max CPU usage per VM over 5-minute windows
- `acm_rs_vm:pod:cpu_request` — CPU request per VM
- `acm_rs_vm:pod:cpu_recommendation_1d` — Daily CPU recommendation per VM
- `acm_rs_vm:pod:memory_usage_max_5m` — Max memory usage per VM
- `acm_rs_vm:pod:memory_request` — Memory request per VM
- `acm_rs_vm:pod:memory_recommendation_1d` — Daily memory recommendation per VM

### Perses dashboard deployment

The Perses dashboards are deployed as `PersesDashboard` custom resources on the hub cluster. They connect to the hub's Thanos Querier as the datasource, querying the federated `acm_rs:*` and `acm_rs_vm:*` metrics that are scraped from managed clusters.

```yaml
apiVersion: perses.dev/v1alpha2
kind: PersesDashboard
metadata:
  name: acm-right-sizing-namespace
  namespace: open-cluster-management-observability
spec:
  # Dashboard definition with panels, variables, and queries
  # targeting acm_rs:namespace:* and acm_rs:cluster:* metrics
```

## Getting started

### Prerequisites

- Red Hat Advanced Cluster Management for Kubernetes 2.17
- Multicluster observability enabled (Prometheus, Thanos)
- Cluster observability operator 1.4+ (for Red Hat build of Perses)
- OpenShift Virtualization (for virtualization right-sizing)
- MCOA deployed with right-sizing delegation enabled

### Enabling right-sizing with MCOA delegation

1. **Ensure MCOA is deployed** with right-sizing capability. Verify the delegation annotation is present on the MCO CR:

```yaml
apiVersion: observability.open-cluster-management.io/v1beta2
kind: MultiClusterObservability
metadata:
  name: observability
  annotations:
    observability.open-cluster-management.io/right-sizing-capable: "true"
spec:
  capabilities:
    platform:
      analytics:
        namespaceRightSizingRecommendation:
          enabled: true
          namespaceBinding: open-cluster-management-global-set
        virtualizationRightSizingRecommendation:
          enabled: true
          namespaceBinding: open-cluster-management-global-set
```

2. **Verify the AddOnDeploymentConfig** is synced with right-sizing state:

```bash
oc get addondeploymentconfig -n open-cluster-management -o yaml | grep -A2 "platformNamespaceRightSizing\|platformVirtualizationRightSizing"
```

3. **Confirm PrometheusRules are deployed** on managed clusters:

```bash
oc get prometheusrule -n openshift-monitoring | grep acm-rs
```

4. **Access Perses dashboards** in the OpenShift console:

   Navigate to **Observe → Dashboards (Perses)** and select the right-sizing namespace or virtualization dashboard.

### Configuration

Right-sizing behavior can be customized through ConfigMaps managed by MCOA on the hub cluster:

**Namespace right-sizing configuration** (`rs-namespace-config`):

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: rs-namespace-config
  namespace: open-cluster-management-observability
data:
  config.yaml: |
    recommendationPercentage: 110
    excludeNamespaces:
      - openshift-*
      - kube-*
    includeLabels:
      - app
      - component
```

**Virtualization right-sizing configuration** (`rs-virt-config`):

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: rs-virt-config
  namespace: open-cluster-management-observability
data:
  config.yaml: |
    recommendationPercentage: 110
    excludeNamespaces:
      - openshift-*
```

### Disclaimers

- This is a **developer preview** release. Perses dashboards for right-sizing are not yet supported for production environments.
- Historical data points are not backfilled. After enabling right-sizing, allow time for data accumulation before analyzing longer aggregation periods.
- The cluster observability operator with Red Hat build of Perses must be deployed separately (technology preview).
- Performance characteristics may vary with large numbers of namespaces or virtual machines.
- The delegation mechanism requires both MCO and MCOA to be at compatible versions (ACM 2.17).

## What's next

This developer preview represents the next step in the right-sizing recommendation journey:

| Release | Milestone | Dashboard |
|---------|-----------|-----------|
| ACM 2.10 (Jul 2024) | [Namespace RS developer preview](https://developers.redhat.com/articles/2024/07/16/improved-right-sizing-experience-red-hat-advanced-cluster-management-kubernetes) | Grafana |
| ACM 2.13 (Mar 2025) | [Virtualization RS developer preview](https://developers.redhat.com/articles/2025/04/28/announcing-right-sizing-openshift-virtualization) | Grafana |
| ACM 2.14 (Aug 2025) | [Namespace RS technology preview](https://developers.redhat.com/articles/2025/08/04/optimize-workloads-right-sizing-recommendations) | Grafana |
| ACM 2.15 (Dec 2025) | [Virtualization RS technology preview](https://developers.redhat.com/articles/2025/12/05/right-sizing-recommendations-openshift-virtualization) | Grafana |
| ACM 2.16 (Mar 2026) | [Namespace + Virtualization RS GA](https://developers.redhat.com/articles/2026/03/17/advanced-cluster-management-216-right-sizing-recommendation-ga) | Grafana |
| ACM 2.17 (2026) | **Namespace + Virtualization RS with Perses (developer preview)** | **Perses** |

Looking ahead, we are working toward:

- **Technology preview** of Perses-based right-sizing dashboards with enhanced interactivity and drill-down capabilities.
- **Workload-level right-sizing** extending recommendations beyond namespaces and VMs to individual workloads and pods.
- **GPU right-sizing** providing optimization insights for GPU-accelerated workloads.
- **Predictive right-sizing** leveraging time-series forecasting to anticipate future resource needs.

We value your feedback. Try the developer preview and share your questions and recommendations using the [Red Hat OpenShift feedback form](https://redhatdg.co1.qualtrics.com/jfe/form/SV_6X9h8MnPno3eg86?source=observability). Your input shapes the path forward.

---

*Related articles:*

- [Improved Right Sizing experience in RHACM (Developer Preview, Jul 2024)](https://developers.redhat.com/articles/2024/07/16/improved-right-sizing-experience-red-hat-advanced-cluster-management-kubernetes)
- [Announcing right-sizing for OpenShift Virtualization (Developer Preview, Apr 2025)](https://developers.redhat.com/articles/2025/04/28/announcing-right-sizing-openshift-virtualization)
- [Optimize workloads with right-sizing recommendations (Technology Preview, Aug 2025)](https://developers.redhat.com/articles/2025/08/04/optimize-workloads-right-sizing-recommendations)
- [Right-sizing recommendations for OpenShift Virtualization (Technology Preview, Dec 2025)](https://developers.redhat.com/articles/2025/12/05/right-sizing-recommendations-openshift-virtualization)
- [Advanced Cluster Management 2.16 right-sizing recommendation GA (Mar 2026)](https://developers.redhat.com/articles/2026/03/17/advanced-cluster-management-216-right-sizing-recommendation-ga)
- [Red Hat build of Perses with the cluster observability operator (Apr 2026)](https://developers.redhat.com/articles/2026/04/02/red-hat-build-perses-cluster-observability-operator)
