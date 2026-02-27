#!/usr/bin/env python3
# Copyright (c) Red Hat, Inc.
# Copyright Contributors to the Open Cluster Management project
# Licensed under the Apache License 2.0

"""
Generate synthetic CPU/memory right-sizing metrics in OpenMetrics format.

This script produces ALL CPU/memory right-sizing metrics — both the raw base
metrics and the derived recording-rule outputs — covering a configurable number
of days so that Prometheus has immediate historical data for dashboards and rule
testing.

Simulated namespaces and utilization profiles:

  Namespace    Utilization  Workloads
  ───────────  ───────────  ─────────────────────────────────────────────
  production   >100% CPU    web-frontend (130%), api-gateway (125%),
                            payment-svc (110%)
  backend      mixed        redis-cache (80%), postgres-db (87.5%),
                            worker-pool (140%)
  monitoring   <30%  CPU    prometheus-main (25%), grafana-dash (15%),
                            alertmanager (16%)
  batch-jobs   mixed        etl-pipeline (125%), data-export-job (30%),
                            ml-training-job (81%)
  development  <80%  CPU    dev-sandbox (12.5%), test-runner (10%),
                            staging-app (75%)
  infra        mixed        ingress-ctrl (80%), dns-server (120%),
                            log-forwarder (70%)

Metric layers generated:
  1. Base / input   — kube_pod_owner, kube_*_owner,
                      kube_pod_container_resource_{requests,limits},
                      node_namespace_pod_container:...:sum_irate,
                      container_memory_working_set_bytes,
                      kube_resourcequota
  2. 5m rules       — acm_rs:{namespace,pod,workload,cluster}:cpu_*:5m
                      acm_rs:{namespace,pod,workload,cluster}:memory_*:5m
  3. 1d rules       — acm_rs:{namespace,pod,workload,cluster}:cpu_*
                      acm_rs:{namespace,pod,workload,cluster}:memory_*
                      (with profile / aggregation labels)

Usage (on a machine with promtool):
  python3 generate-cpu-mock-data.py --days 5 -o /tmp/cpu-mock.om
  promtool tsdb create-blocks-from openmetrics /tmp/cpu-mock.om /tmp/cpu-blocks

Generate / regenerate the live PrometheusRule YAML:
  python3 generate-cpu-mock-data.py --live-yaml cpu-base-metrics-mock-prometheusrule.yaml

Import into OpenShift Prometheus:
  ./import-cpu-mock-to-ocp.sh            # uses default 5 days
  ./import-cpu-mock-to-ocp.sh 10         # override to 10 days
"""

from __future__ import annotations

import argparse
import math
import sys
import time

# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────
OMEGA = 2 * math.pi / 18000  # 5-hour sinusoidal period
OMEGA_STR = "0.000349066"  # truncated representation for YAML exprs
CLUSTER = "local-cluster"
REC_PCT = 110  # default recommendationPercentage from Go code
STEP = 300  # 5-minute sample interval (seconds)

# ──────────────────────────────────────────────────────────────────────
# Workload definitions — 6 namespaces, 18 pods, diverse utilization
# ──────────────────────────────────────────────────────────────────────
#
# CPU values are in cores (float).  Memory values are in bytes.
# Utilization = usage / request.
#
# Key fields per pod:
#   cpu_req, cpu_lim   — resource requests/limits in cores
#   cb, ca             — CPU usage base / amplitude (sinusoidal)
#   mem_req, mem_lim   — resource requests/limits in bytes
#   mb, ma             — memory usage base / amplitude (sinusoidal)
#   phase              — sinusoidal phase offset (radians)
#
# fmt: off
ALL_PODS = [
    # ── production (over-utilized — usage > request) ────────────────
    dict(ns="production", pod="web-frontend-a1b2c",   workload="web-frontend", wtype="Deployment",
         owner_kind="ReplicaSet", owner_name="web-frontend-6f8d4a",
         cpu_req=0.5,  cpu_lim=1.0,  cb=0.65, ca=0.12,          # avg ~130%
         mem_req=268_435_456,   mem_lim=536_870_912,             # 256Mi / 512Mi
         mb=310_000_000,  ma=30_000_000,                         # avg ~117%
         phase=0.10),
    dict(ns="production", pod="api-gateway-x3y4z",    workload="api-gateway",  wtype="Deployment",
         owner_kind="ReplicaSet", owner_name="api-gateway-3b5d8f",
         cpu_req=1.0,  cpu_lim=2.0,  cb=1.25, ca=0.15,          # avg ~125%
         mem_req=536_870_912,   mem_lim=1_073_741_824,           # 512Mi / 1Gi
         mb=600_000_000,  ma=50_000_000,                         # avg ~117%
         phase=0.90),
    dict(ns="production", pod="payment-svc-p5q6r",    workload="payment-svc",  wtype="Deployment",
         owner_kind="ReplicaSet", owner_name="payment-svc-2c4e6g",
         cpu_req=0.5,  cpu_lim=1.0,  cb=0.55, ca=0.08,          # avg ~110%
         mem_req=268_435_456,   mem_lim=536_870_912,             # 256Mi / 512Mi
         mb=200_000_000,  ma=25_000_000,                         # avg ~78%
         phase=1.60),

    # ── backend (moderate — mixed utilization) ──────────────────────
    dict(ns="backend", pod="redis-cache-0",            workload="redis-cache",  wtype="StatefulSet",
         owner_kind="StatefulSet", owner_name="redis-cache",
         cpu_req=2.0,  cpu_lim=3.0,  cb=1.6,  ca=0.25,          # avg ~80%
         mem_req=4_294_967_296,  mem_lim=6_442_450_944,          # 4Gi / 6Gi
         mb=3_500_000_000,  ma=300_000_000,                      # avg ~81%
         phase=2.40),
    dict(ns="backend", pod="postgres-db-0",            workload="postgres-db",  wtype="StatefulSet",
         owner_kind="StatefulSet", owner_name="postgres-db",
         cpu_req=4.0,  cpu_lim=6.0,  cb=3.5,  ca=0.30,          # avg ~87.5%
         mem_req=8_589_934_592,  mem_lim=12_884_901_888,         # 8Gi / 12Gi
         mb=7_000_000_000,  ma=500_000_000,                      # avg ~81%
         phase=3.10),
    dict(ns="backend", pod="worker-pool-m7n8o",        workload="worker-pool",  wtype="Deployment",
         owner_kind="ReplicaSet", owner_name="worker-pool-4d6f8h",
         cpu_req=2.0,  cpu_lim=4.0,  cb=2.8,  ca=0.30,          # avg ~140%
         mem_req=1_073_741_824,  mem_lim=2_147_483_648,          # 1Gi / 2Gi
         mb=1_200_000_000,  ma=100_000_000,                      # avg ~112%
         phase=3.90),

    # ── monitoring (very under-utilized — massive over-provision) ──
    dict(ns="monitoring", pod="prometheus-main-0",     workload="prometheus-main", wtype="StatefulSet",
         owner_kind="StatefulSet", owner_name="prometheus-main",
         cpu_req=4.0,  cpu_lim=8.0,  cb=1.0,  ca=0.20,          # avg ~25%
         mem_req=8_589_934_592,  mem_lim=12_884_901_888,         # 8Gi / 12Gi
         mb=3_000_000_000,  ma=400_000_000,                      # avg ~35%
         phase=0.30),
    dict(ns="monitoring", pod="grafana-dash-s9t0u",    workload="grafana-dash",   wtype="Deployment",
         owner_kind="ReplicaSet", owner_name="grafana-dash-8j2k4l",
         cpu_req=1.0,  cpu_lim=2.0,  cb=0.15, ca=0.05,          # avg ~15%
         mem_req=536_870_912,    mem_lim=1_073_741_824,          # 512Mi / 1Gi
         mb=180_000_000,  ma=30_000_000,                         # avg ~33%
         phase=1.20),
    dict(ns="monitoring", pod="alertmanager-0",        workload="alertmanager",   wtype="StatefulSet",
         owner_kind="StatefulSet", owner_name="alertmanager",
         cpu_req=0.5,  cpu_lim=1.0,  cb=0.08, ca=0.02,          # avg ~16%
         mem_req=268_435_456,    mem_lim=536_870_912,            # 256Mi / 512Mi
         mb=64_000_000,   ma=10_000_000,                         # avg ~24%
         phase=2.50),

    # ── batch-jobs (bursty — some over, some under) ────────────────
    dict(ns="batch-jobs", pod="etl-pipeline-28930200-v1w2x", workload="etl-pipeline", wtype="CronJob",
         owner_kind="Job", owner_name="etl-pipeline-28930200",
         cpu_req=2.0,  cpu_lim=4.0,  cb=2.5,  ca=0.40,          # avg ~125%
         mem_req=2_147_483_648,  mem_lim=4_294_967_296,          # 2Gi / 4Gi
         mb=1_800_000_000,  ma=200_000_000,                      # avg ~84%
         phase=0.70),
    dict(ns="batch-jobs", pod="data-export-job-xyz",   workload="data-export-job",  wtype="Job",
         owner_kind="Job", owner_name="data-export-job",
         cpu_req=1.0,  cpu_lim=2.0,  cb=0.30, ca=0.08,          # avg ~30%
         mem_req=536_870_912,    mem_lim=1_073_741_824,          # 512Mi / 1Gi
         mb=128_000_000,  ma=20_000_000,                         # avg ~24%
         phase=1.80),
    dict(ns="batch-jobs", pod="ml-training-job-abc",   workload="ml-training-job",  wtype="Job",
         owner_kind="Job", owner_name="ml-training-job",
         cpu_req=8.0,  cpu_lim=10.0, cb=6.5,  ca=0.80,          # avg ~81%
         mem_req=17_179_869_184, mem_lim=21_474_836_480,         # 16Gi / 20Gi
         mb=14_000_000_000, ma=1_000_000_000,                    # avg ~81%
         phase=3.40),

    # ── development (heavily over-provisioned — very low usage) ────
    dict(ns="development", pod="dev-sandbox-d3e4f",    workload="dev-sandbox",  wtype="Deployment",
         owner_kind="ReplicaSet", owner_name="dev-sandbox-5g7h9j",
         cpu_req=4.0,  cpu_lim=6.0,  cb=0.50, ca=0.15,          # avg ~12.5%
         mem_req=8_589_934_592,  mem_lim=12_884_901_888,         # 8Gi / 12Gi
         mb=512_000_000,  ma=80_000_000,                         # avg ~6%
         phase=0.50),
    dict(ns="development", pod="test-runner-g5h6i",    workload="test-runner",  wtype="Deployment",
         owner_kind="ReplicaSet", owner_name="test-runner-1k3l5m",
         cpu_req=2.0,  cpu_lim=4.0,  cb=0.20, ca=0.06,          # avg ~10%
         mem_req=4_294_967_296,  mem_lim=6_442_450_944,          # 4Gi / 6Gi
         mb=200_000_000,  ma=40_000_000,                         # avg ~5%
         phase=2.10),
    dict(ns="development", pod="staging-app-j7k8l",    workload="staging-app",  wtype="Deployment",
         owner_kind="ReplicaSet", owner_name="staging-app-6n8o0p",
         cpu_req=2.0,  cpu_lim=4.0,  cb=1.50, ca=0.20,          # avg ~75%
         mem_req=2_147_483_648,  mem_lim=4_294_967_296,          # 2Gi / 4Gi
         mb=1_500_000_000,  ma=200_000_000,                      # avg ~70%
         phase=2.70),

    # ── infra (networking & logging — mixed) ───────────────────────
    dict(ns="infra", pod="ingress-ctrl-node1",         workload="ingress-ctrl", wtype="DaemonSet",
         owner_kind="DaemonSet", owner_name="ingress-ctrl",
         cpu_req=0.5,  cpu_lim=1.0,  cb=0.40, ca=0.06,          # avg ~80%
         mem_req=268_435_456,    mem_lim=536_870_912,            # 256Mi / 512Mi
         mb=200_000_000,  ma=25_000_000,                         # avg ~74%
         phase=0.90),
    dict(ns="infra", pod="dns-server-m9n0o",           workload="dns-server",   wtype="Deployment",
         owner_kind="ReplicaSet", owner_name="dns-server-2p4q6r",
         cpu_req=0.25, cpu_lim=0.5,  cb=0.30, ca=0.04,          # avg ~120%
         mem_req=134_217_728,    mem_lim=268_435_456,            # 128Mi / 256Mi
         mb=150_000_000,  ma=15_000_000,                         # avg ~112%
         phase=1.60),
    dict(ns="infra", pod="log-forwarder-node1",        workload="log-forwarder", wtype="DaemonSet",
         owner_kind="DaemonSet", owner_name="log-forwarder",
         cpu_req=0.5,  cpu_lim=1.0,  cb=0.35, ca=0.05,          # avg ~70%
         mem_req=268_435_456,    mem_lim=536_870_912,            # 256Mi / 512Mi
         mb=150_000_000,  ma=20_000_000,                         # avg ~56%
         phase=2.40),
]
# fmt: on

# Namespace-level resource quotas  (hard limits)
NS_QUOTAS: dict[str, dict[str, float]] = {
    "production":  {"cpu": 10.0, "memory": 21_474_836_480},   # 10 CPU, 20Gi
    "backend":     {"cpu": 20.0, "memory": 42_949_672_960},   # 20 CPU, 40Gi
    "monitoring":  {"cpu": 10.0, "memory": 21_474_836_480},   # 10 CPU, 20Gi
    "batch-jobs":  {"cpu": 16.0, "memory": 32_212_254_720},   # 16 CPU, 30Gi
    "development": {"cpu": 12.0, "memory": 26_843_545_600},   # 12 CPU, 25Gi
    "infra":       {"cpu":  4.0, "memory":  5_368_709_120},   #  4 CPU,  5Gi
}

# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _sin(t: int, base: float, amp: float, phase: float) -> float:
    return base + amp * math.sin(t * OMEGA + phase)


def _labels(**kwargs: str | float) -> str:
    return "{" + ",".join(f'{k}="{v}"' for k, v in kwargs.items()) + "}"


def _emit(out, name: str, ls: str, timestamps: list[int], values: list[float]) -> None:
    """Write samples for one label-set as a batch."""
    lines = []
    for ts, v in zip(timestamps, values):
        lines.append(f"{name}{ls} {v:.6g} {ts}\n")
    out.writelines(lines)


def _rolling_max(values: list[float], window: int) -> list[float]:
    """Simple rolling max — O(n·w) but fine for our data sizes."""
    out: list[float] = []
    for i in range(len(values)):
        lo = max(0, i - window + 1)
        out.append(max(values[lo : i + 1]))
    return out


def _num(v: float | int) -> str:
    """Format a number for YAML / PromQL expressions (integer if whole)."""
    if isinstance(v, int):
        return str(v)
    if v == int(v):
        return str(int(v))
    return f"{v:g}"


def _group_by_ns() -> dict[str, list[dict]]:
    """Return ALL_PODS grouped by namespace (preserving order)."""
    ns_pods: dict[str, list[dict]] = {}
    for p in ALL_PODS:
        ns_pods.setdefault(p["ns"], []).append(p)
    return ns_pods


# ──────────────────────────────────────────────────────────────────────
# Metric definitions
# ──────────────────────────────────────────────────────────────────────

# Pod-level metrics:  (recording rule suffix, request_key_or_None, val_key)
# If request_key_or_None is not None → value is constant (request/limit).
# Otherwise val_key names the sinusoidal data.
_POD_METRICS_CPU = [
    ("cpu_request", "cpu_req"),
    ("cpu_limit",   "cpu_lim"),
    ("cpu_usage",   None),      # sinusoidal
]
_POD_METRICS_MEM = [
    ("memory_request", "mem_req"),
    ("memory_limit",   "mem_lim"),
    ("memory_usage",   None),   # sinusoidal
]

# ──────────────────────────────────────────────────────────────────────
# OpenMetrics generation
# ──────────────────────────────────────────────────────────────────────


def _generate_openmetrics(out, days: float) -> None:
    """Generate OpenMetrics data for the configured duration."""
    end_ts = int(time.time())
    start_ts = end_ts - int(days * 86400)
    timestamps = list(range(start_ts, end_ts + 1, STEP))
    n = len(timestamps)
    window_1d = min(288, n)  # 24 h / 5 min = 288 samples

    ns_pods = _group_by_ns()
    print(
        f"Generating {n} samples × {len(ALL_PODS)} pods across "
        f"{len(ns_pods)} namespaces ({days} days) …",
        file=sys.stderr,
    )

    # ── Pre-compute per-pod sinusoidal values ────────────────────
    pod_cpu: dict[str, list[float]] = {}
    pod_mem: dict[str, list[float]] = {}
    for p in ALL_PODS:
        ph = p["phase"]
        pod_cpu[p["pod"]] = [_sin(t, p["cb"], p["ca"], ph) for t in timestamps]
        pod_mem[p["pod"]] = [_sin(t, p["mb"], p["ma"], ph) for t in timestamps]

    # ═══════════════════════════════════════════════════════════════
    # 1. BASE / INPUT METRICS
    # ═══════════════════════════════════════════════════════════════

    # ── kube_pod_owner ──
    out.write("# TYPE kube_pod_owner gauge\n")
    for p in ALL_PODS:
        ls = _labels(
            cluster=CLUSTER, namespace=p["ns"], pod=p["pod"],
            owner_kind=p["owner_kind"], owner_name=p["owner_name"],
        )
        _emit(out, "kube_pod_owner", ls, timestamps, [1.0] * n)

    # ── kube_replicaset_owner (Deployment path only) ──
    out.write("# TYPE kube_replicaset_owner gauge\n")
    for p in ALL_PODS:
        if p["owner_kind"] == "ReplicaSet" and p["wtype"] == "Deployment":
            ls = _labels(
                cluster=CLUSTER, namespace=p["ns"],
                replicaset=p["owner_name"], owner_kind="Deployment", owner_name=p["workload"],
            )
            _emit(out, "kube_replicaset_owner", ls, timestamps, [1.0] * n)

    # ── kube_job_owner (CronJob path only) ──
    out.write("# TYPE kube_job_owner gauge\n")
    for p in ALL_PODS:
        if p["owner_kind"] == "Job" and p["wtype"] == "CronJob":
            ls = _labels(
                cluster=CLUSTER, namespace=p["ns"],
                job_name=p["owner_name"], owner_kind="CronJob", owner_name=p["workload"],
            )
            _emit(out, "kube_job_owner", ls, timestamps, [1.0] * n)

    # ── kube_pod_container_resource_requests (CPU) ──
    out.write("# TYPE kube_pod_container_resource_requests gauge\n")
    for p in ALL_PODS:
        # CPU request
        ls = _labels(
            cluster=CLUSTER, namespace=p["ns"], pod=p["pod"],
            container="main", resource="cpu", unit="core",
        )
        _emit(out, "kube_pod_container_resource_requests", ls, timestamps, [float(p["cpu_req"])] * n)
        # Memory request
        ls = _labels(
            cluster=CLUSTER, namespace=p["ns"], pod=p["pod"],
            container="main", resource="memory", unit="byte",
        )
        _emit(out, "kube_pod_container_resource_requests", ls, timestamps, [float(p["mem_req"])] * n)

    # ── kube_pod_container_resource_limits (CPU + memory) ──
    out.write("# TYPE kube_pod_container_resource_limits gauge\n")
    for p in ALL_PODS:
        # CPU limit
        ls = _labels(
            cluster=CLUSTER, namespace=p["ns"], pod=p["pod"],
            container="main", resource="cpu", unit="core",
        )
        _emit(out, "kube_pod_container_resource_limits", ls, timestamps, [float(p["cpu_lim"])] * n)
        # Memory limit
        ls = _labels(
            cluster=CLUSTER, namespace=p["ns"], pod=p["pod"],
            container="main", resource="memory", unit="byte",
        )
        _emit(out, "kube_pod_container_resource_limits", ls, timestamps, [float(p["mem_lim"])] * n)

    # ── CPU usage (sinusoidal) ──
    out.write("# TYPE node_namespace_pod_container:container_cpu_usage_seconds_total:sum_irate gauge\n")
    for p in ALL_PODS:
        ls = _labels(cluster=CLUSTER, namespace=p["ns"], pod=p["pod"], container="main")
        _emit(out, "node_namespace_pod_container:container_cpu_usage_seconds_total:sum_irate",
              ls, timestamps, pod_cpu[p["pod"]])

    # ── Memory usage (sinusoidal) ──
    out.write("# TYPE container_memory_working_set_bytes gauge\n")
    for p in ALL_PODS:
        ls = _labels(cluster=CLUSTER, namespace=p["ns"], pod=p["pod"], container="main")
        _emit(out, "container_memory_working_set_bytes", ls, timestamps, pod_mem[p["pod"]])

    # ── Resource quotas ──
    out.write("# TYPE kube_resourcequota gauge\n")
    for ns_name, quota in NS_QUOTAS.items():
        # CPU quota
        ls = _labels(
            cluster=CLUSTER, namespace=ns_name,
            resource="requests.cpu", type="hard", resourcequota=f"{ns_name}-quota",
        )
        _emit(out, "kube_resourcequota", ls, timestamps, [quota["cpu"]] * n)
        # Memory quota
        ls = _labels(
            cluster=CLUSTER, namespace=ns_name,
            resource="requests.memory", type="hard", resourcequota=f"{ns_name}-quota",
        )
        _emit(out, "kube_resourcequota", ls, timestamps, [quota["memory"]] * n)

    # ═══════════════════════════════════════════════════════════════
    # 2. RECORDING-RULE OUTPUTS — 5m
    # ═══════════════════════════════════════════════════════════════

    # ── Pod-workload mapping (constant 1) ──
    out.write("# TYPE acm_rs:pod_workload:relabel:5m gauge\n")
    for p in ALL_PODS:
        ls = _labels(
            cluster=CLUSTER, namespace=p["ns"], pod=p["pod"],
            workload=p["workload"], workload_type=p["wtype"],
        )
        _emit(out, "acm_rs:pod_workload:relabel:5m", ls, timestamps, [1.0] * n)

    # ── Namespace-level 5m ──
    # Compute per-namespace aggregations
    all_ns_5m: dict[str, dict[str, list[float]]] = {}
    for ns_name, pods in ns_pods.items():
        ns_5m: dict[str, list[float]] = {
            "cpu_request_hard": [NS_QUOTAS[ns_name]["cpu"]] * n,
            "cpu_request":  [sum(p["cpu_req"] for p in pods)] * n,
            "cpu_usage":    [sum(pod_cpu[p["pod"]][i] for p in pods) for i in range(n)],
            "memory_request_hard": [NS_QUOTAS[ns_name]["memory"]] * n,
            "memory_request": [sum(p["mem_req"] for p in pods)] * n,
            "memory_usage": [sum(pod_mem[p["pod"]][i] for p in pods) for i in range(n)],
        }
        all_ns_5m[ns_name] = ns_5m

    ns_5m_keys = [
        "cpu_request_hard", "cpu_request", "cpu_usage",
        "memory_request_hard", "memory_request", "memory_usage",
    ]
    for suffix in ns_5m_keys:
        name = f"acm_rs:namespace:{suffix}:5m"
        out.write(f"# TYPE {name} gauge\n")
        for ns_name in ns_pods:
            ls = _labels(cluster=CLUSTER, namespace=ns_name)
            _emit(out, name, ls, timestamps, all_ns_5m[ns_name][suffix])

    # ── Pod-level 5m ──
    for suffix, req_key in _POD_METRICS_CPU:
        name = f"acm_rs:pod:{suffix}:5m"
        out.write(f"# TYPE {name} gauge\n")
        for p in ALL_PODS:
            ls = _labels(
                cluster=CLUSTER, namespace=p["ns"], pod=p["pod"],
                workload=p["workload"], workload_type=p["wtype"],
            )
            vals = [float(p[req_key])] * n if req_key else pod_cpu[p["pod"]]
            _emit(out, name, ls, timestamps, vals)

    for suffix, req_key in _POD_METRICS_MEM:
        name = f"acm_rs:pod:{suffix}:5m"
        out.write(f"# TYPE {name} gauge\n")
        for p in ALL_PODS:
            ls = _labels(
                cluster=CLUSTER, namespace=p["ns"], pod=p["pod"],
                workload=p["workload"], workload_type=p["wtype"],
            )
            vals = [float(p[req_key])] * n if req_key else pod_mem[p["pod"]]
            _emit(out, name, ls, timestamps, vals)

    # ── Workload-level 5m (1 pod per workload in this mock) ──
    for suffix, req_key in _POD_METRICS_CPU:
        name = f"acm_rs:workload:{suffix}:5m"
        out.write(f"# TYPE {name} gauge\n")
        for p in ALL_PODS:
            ls = _labels(
                cluster=CLUSTER, namespace=p["ns"],
                workload=p["workload"], workload_type=p["wtype"],
            )
            vals = [float(p[req_key])] * n if req_key else pod_cpu[p["pod"]]
            _emit(out, name, ls, timestamps, vals)

    for suffix, req_key in _POD_METRICS_MEM:
        name = f"acm_rs:workload:{suffix}:5m"
        out.write(f"# TYPE {name} gauge\n")
        for p in ALL_PODS:
            ls = _labels(
                cluster=CLUSTER, namespace=p["ns"],
                workload=p["workload"], workload_type=p["wtype"],
            )
            vals = [float(p[req_key])] * n if req_key else pod_mem[p["pod"]]
            _emit(out, name, ls, timestamps, vals)

    # ── Cluster-level 5m ──
    nss = list(ns_pods.keys())
    cl_5m: dict[str, list[float]] = {
        "cpu_request_hard":    [sum(NS_QUOTAS[ns]["cpu"] for ns in nss)] * n,
        "cpu_request":         [sum(all_ns_5m[ns]["cpu_request"][0] for ns in nss)] * n,
        "cpu_usage":           [sum(all_ns_5m[ns]["cpu_usage"][i] for ns in nss) for i in range(n)],
        "memory_request_hard": [sum(NS_QUOTAS[ns]["memory"] for ns in nss)] * n,
        "memory_request":      [sum(all_ns_5m[ns]["memory_request"][0] for ns in nss)] * n,
        "memory_usage":        [sum(all_ns_5m[ns]["memory_usage"][i] for ns in nss) for i in range(n)],
    }

    cl_5m_keys = [
        "cpu_request_hard", "cpu_request", "cpu_usage",
        "memory_request_hard", "memory_request", "memory_usage",
    ]
    for suffix in cl_5m_keys:
        name = f"acm_rs:cluster:{suffix}:5m"
        out.write(f"# TYPE {name} gauge\n")
        ls = _labels(cluster=CLUSTER)
        _emit(out, name, ls, timestamps, cl_5m[suffix])

    # ═══════════════════════════════════════════════════════════════
    # 3. RECORDING-RULE OUTPUTS — 1d  (profile="Max OverAll")
    # ═══════════════════════════════════════════════════════════════
    extra = {"profile": "Max OverAll", "aggregation": "1d"}

    # ── Namespace-level 1d ──
    for ns_name in ns_pods:
        ns_5m_data = all_ns_5m[ns_name]
        for suffix in ns_5m_keys:
            name = f"acm_rs:namespace:{suffix}"
            out.write(f"# TYPE {name} gauge\n")
            ls = _labels(cluster=CLUSTER, namespace=ns_name, **extra)
            _emit(out, name, ls, timestamps, _rolling_max(ns_5m_data[suffix], window_1d))

        # Recommendations
        for rec_suffix, src_suffix in [
            ("cpu_recommendation", "cpu_usage"),
            ("memory_recommendation", "memory_usage"),
        ]:
            name = f"acm_rs:namespace:{rec_suffix}"
            out.write(f"# TYPE {name} gauge\n")
            ls = _labels(cluster=CLUSTER, namespace=ns_name, **extra)
            base = _rolling_max(ns_5m_data[src_suffix], window_1d)
            _emit(out, name, ls, timestamps, [v * REC_PCT / 100 for v in base])

    # ── Pod-level 1d ──
    for suffix, req_key in _POD_METRICS_CPU:
        name = f"acm_rs:pod:{suffix}"
        out.write(f"# TYPE {name} gauge\n")
        for p in ALL_PODS:
            ls = _labels(
                cluster=CLUSTER, namespace=p["ns"], pod=p["pod"],
                workload=p["workload"], workload_type=p["wtype"], **extra,
            )
            raw = [float(p[req_key])] * n if req_key else pod_cpu[p["pod"]]
            _emit(out, name, ls, timestamps, _rolling_max(raw, window_1d))

    for suffix, req_key in _POD_METRICS_MEM:
        name = f"acm_rs:pod:{suffix}"
        out.write(f"# TYPE {name} gauge\n")
        for p in ALL_PODS:
            ls = _labels(
                cluster=CLUSTER, namespace=p["ns"], pod=p["pod"],
                workload=p["workload"], workload_type=p["wtype"], **extra,
            )
            raw = [float(p[req_key])] * n if req_key else pod_mem[p["pod"]]
            _emit(out, name, ls, timestamps, _rolling_max(raw, window_1d))

    # Pod recommendations
    for rec_suffix, src_data in [
        ("cpu_recommendation", pod_cpu),
        ("memory_recommendation", pod_mem),
    ]:
        name = f"acm_rs:pod:{rec_suffix}"
        out.write(f"# TYPE {name} gauge\n")
        for p in ALL_PODS:
            ls = _labels(
                cluster=CLUSTER, namespace=p["ns"], pod=p["pod"],
                workload=p["workload"], workload_type=p["wtype"], **extra,
            )
            base = _rolling_max(src_data[p["pod"]], window_1d)
            _emit(out, name, ls, timestamps, [v * REC_PCT / 100 for v in base])

    # ── Workload-level 1d ──
    for suffix, req_key in _POD_METRICS_CPU:
        name = f"acm_rs:workload:{suffix}"
        out.write(f"# TYPE {name} gauge\n")
        for p in ALL_PODS:
            ls = _labels(
                cluster=CLUSTER, namespace=p["ns"],
                workload=p["workload"], workload_type=p["wtype"], **extra,
            )
            raw = [float(p[req_key])] * n if req_key else pod_cpu[p["pod"]]
            _emit(out, name, ls, timestamps, _rolling_max(raw, window_1d))

    for suffix, req_key in _POD_METRICS_MEM:
        name = f"acm_rs:workload:{suffix}"
        out.write(f"# TYPE {name} gauge\n")
        for p in ALL_PODS:
            ls = _labels(
                cluster=CLUSTER, namespace=p["ns"],
                workload=p["workload"], workload_type=p["wtype"], **extra,
            )
            raw = [float(p[req_key])] * n if req_key else pod_mem[p["pod"]]
            _emit(out, name, ls, timestamps, _rolling_max(raw, window_1d))

    # Workload recommendations
    for rec_suffix, src_data in [
        ("cpu_recommendation", pod_cpu),
        ("memory_recommendation", pod_mem),
    ]:
        name = f"acm_rs:workload:{rec_suffix}"
        out.write(f"# TYPE {name} gauge\n")
        for p in ALL_PODS:
            ls = _labels(
                cluster=CLUSTER, namespace=p["ns"],
                workload=p["workload"], workload_type=p["wtype"], **extra,
            )
            base = _rolling_max(src_data[p["pod"]], window_1d)
            _emit(out, name, ls, timestamps, [v * REC_PCT / 100 for v in base])

    # ── Cluster-level 1d ──
    for suffix in cl_5m_keys:
        name = f"acm_rs:cluster:{suffix}"
        out.write(f"# TYPE {name} gauge\n")
        ls = _labels(cluster=CLUSTER, **extra)
        _emit(out, name, ls, timestamps, _rolling_max(cl_5m[suffix], window_1d))

    for rec_suffix, src_suffix in [
        ("cpu_recommendation", "cpu_usage"),
        ("memory_recommendation", "memory_usage"),
    ]:
        name = f"acm_rs:cluster:{rec_suffix}"
        out.write(f"# TYPE {name} gauge\n")
        ls = _labels(cluster=CLUSTER, **extra)
        base = _rolling_max(cl_5m[src_suffix], window_1d)
        _emit(out, name, ls, timestamps, [v * REC_PCT / 100 for v in base])

    # ── End ──
    out.write("# EOF\n")

    if out is not sys.stdout:
        out.close()

    print("Done.", file=sys.stderr)


# ──────────────────────────────────────────────────────────────────────
# Live PrometheusRule YAML generation
# ──────────────────────────────────────────────────────────────────────

_YAML_HEADER = """\
# Synthetic CPU/memory base metrics for ACM right-sizing recording rules.
#
# *** AUTO-GENERATED — do not edit manually ***
# Regenerate:
#   python3 generate-cpu-mock-data.py --live-yaml cpu-base-metrics-mock-prometheusrule.yaml
#
# This manifest creates only INPUT metrics consumed by:
# - operators/multiclusterobservability/controllers/analytics/rightsizing/rs-namespace/prometheusrule.go
# - operators/multiclusterobservability/controllers/analytics/rightsizing/rs-workload/prometheusrule.go
#
# Notes:
# - CPU usage values follow a 5-hour sinusoidal cycle.
# - Recording rules do not backfill; keep running for 5h to get a full window.
# - Over-utilized workloads intentionally have usage > request.
#
# Apply:
#   oc apply -f docs/rightsizing/cpu-base-metrics-mock-prometheusrule.yaml
#
# Cleanup:
#   oc -n openshift-monitoring delete prometheusrule acm-cpu-base-metrics-mock
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: acm-cpu-base-metrics-mock
  namespace: openshift-monitoring
  labels:
    prometheus: k8s
    role: alert-rules
spec:
  groups:
"""


def _yaml_rule(f, record: str, expr: str, labels: dict[str, str | float]) -> None:
    """Write one YAML recording rule."""
    f.write(f"        - record: {record}\n")
    f.write(f"          expr: {expr}\n")
    f.write("          labels:\n")
    for k, v in labels.items():
        f.write(f"            {k}: {v}\n")


def _generate_live_yaml(path: str) -> None:
    """Generate the PrometheusRule YAML for ongoing live mock data."""
    with open(path, "w") as f:
        f.write(_YAML_HEADER)

        # ── Group 1: Owner rules ──────────────────────────────────
        f.write("    - name: acm-cpu-base-mock-owners.rules\n")
        f.write("      interval: 1m\n")
        f.write("      rules:\n")

        for p in ALL_PODS:
            _yaml_rule(f, "kube_pod_owner", "vector(1)", {
                "cluster": CLUSTER, "namespace": p["ns"], "pod": p["pod"],
                "owner_kind": p["owner_kind"], "owner_name": p["owner_name"],
            })

            # Deployment path: ReplicaSet → Deployment
            if p["owner_kind"] == "ReplicaSet" and p["wtype"] == "Deployment":
                _yaml_rule(f, "kube_replicaset_owner", "vector(1)", {
                    "cluster": CLUSTER, "namespace": p["ns"],
                    "replicaset": p["owner_name"],
                    "owner_kind": "Deployment", "owner_name": p["workload"],
                })

            # CronJob path: Job → CronJob
            if p["owner_kind"] == "Job" and p["wtype"] == "CronJob":
                _yaml_rule(f, "kube_job_owner", "vector(1)", {
                    "cluster": CLUSTER, "namespace": p["ns"],
                    "job_name": p["owner_name"],
                    "owner_kind": "CronJob", "owner_name": p["workload"],
                })

        # ── Group 2: Resource requests & limits ───────────────────
        f.write("\n    - name: acm-cpu-base-mock-requests.rules\n")
        f.write("      interval: 1m\n")
        f.write("      rules:\n")

        for p in ALL_PODS:
            # CPU request
            _yaml_rule(f, "kube_pod_container_resource_requests", f"vector({_num(p['cpu_req'])})", {
                "cluster": CLUSTER, "namespace": p["ns"], "pod": p["pod"],
                "container": "main", "resource": "cpu", "unit": "core",
            })
            # Memory request
            _yaml_rule(f, "kube_pod_container_resource_requests", f"vector({_num(p['mem_req'])})", {
                "cluster": CLUSTER, "namespace": p["ns"], "pod": p["pod"],
                "container": "main", "resource": "memory", "unit": "byte",
            })
            # CPU limit
            _yaml_rule(f, "kube_pod_container_resource_limits", f"vector({_num(p['cpu_lim'])})", {
                "cluster": CLUSTER, "namespace": p["ns"], "pod": p["pod"],
                "container": "main", "resource": "cpu", "unit": "core",
            })
            # Memory limit
            _yaml_rule(f, "kube_pod_container_resource_limits", f"vector({_num(p['mem_lim'])})", {
                "cluster": CLUSTER, "namespace": p["ns"], "pod": p["pod"],
                "container": "main", "resource": "memory", "unit": "byte",
            })

        # ── Group 3: Resource quotas ──────────────────────────────
        f.write("\n    - name: acm-cpu-base-mock-quotas.rules\n")
        f.write("      interval: 1m\n")
        f.write("      rules:\n")

        for ns_name, quota in NS_QUOTAS.items():
            _yaml_rule(f, "kube_resourcequota", f"vector({_num(quota['cpu'])})", {
                "cluster": CLUSTER, "namespace": ns_name,
                "resource": "requests.cpu", "type": "hard",
                "resourcequota": f"{ns_name}-quota",
            })
            _yaml_rule(f, "kube_resourcequota", f"vector({_num(quota['memory'])})", {
                "cluster": CLUSTER, "namespace": ns_name,
                "resource": "requests.memory", "type": "hard",
                "resourcequota": f"{ns_name}-quota",
            })

        # ── Group 4: CPU usage (sinusoidal) ──────────────────────
        f.write("\n    - name: acm-cpu-base-mock-usage.rules\n")
        f.write("      interval: 1m\n")
        f.write("      rules:\n")

        f.write("        # CPU usage (cores) — sinusoidal\n")
        for p in ALL_PODS:
            base = _num(p["cb"])
            amp = _num(p["ca"])
            phase = p["phase"]
            expr = f"{base} + {amp} * sin(vector(time() * {OMEGA_STR} + {phase}))"
            _yaml_rule(
                f,
                "node_namespace_pod_container:container_cpu_usage_seconds_total:sum_irate",
                expr,
                {"cluster": CLUSTER, "namespace": p["ns"], "pod": p["pod"], "container": "main"},
            )

        f.write("        # Memory usage (bytes) — sinusoidal\n")
        for p in ALL_PODS:
            base = _num(p["mb"])
            amp = _num(p["ma"])
            phase = p["phase"]
            expr = f"{base} + {amp} * sin(vector(time() * {OMEGA_STR} + {phase}))"
            _yaml_rule(
                f,
                "container_memory_working_set_bytes",
                expr,
                {"cluster": CLUSTER, "namespace": p["ns"], "pod": p["pod"], "container": "main"},
            )

    print(f"Live PrometheusRule YAML written to: {path}", file=sys.stderr)


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=float, default=5, help="Days of historical data (default: 5)")
    ap.add_argument("-o", "--output", default="-", help="Output file for OpenMetrics data (default: stdout)")
    ap.add_argument(
        "--live-yaml",
        default=None,
        metavar="FILE",
        help="Generate the PrometheusRule YAML for live mock data (in addition to OpenMetrics output)",
    )
    args = ap.parse_args()

    # Generate live YAML if requested
    if args.live_yaml:
        _generate_live_yaml(args.live_yaml)

    # Generate OpenMetrics data
    out = sys.stdout if args.output == "-" else open(args.output, "w")  # noqa: SIM115
    _generate_openmetrics(out, args.days)


if __name__ == "__main__":
    main()
