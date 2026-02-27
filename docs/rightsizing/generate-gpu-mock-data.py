#!/usr/bin/env python3
# Copyright (c) Red Hat, Inc.
# Copyright Contributors to the Open Cluster Management project
# Licensed under the Apache License 2.0

"""
Generate synthetic GPU right-sizing metrics in OpenMetrics format.

This script produces ALL GPU right-sizing metrics — both the raw base metrics
and the derived recording-rule outputs — covering a configurable number of days
so that Prometheus has immediate historical data for dashboards and rule testing.

Simulated namespaces and GPU types:

  Namespace          GPU Model(s)            Workloads
  ─────────────────  ──────────────────────  ─────────────────────────────────
  gpu-demo           NVIDIA A10 24 GB        Deployment, StatefulSet, DaemonSet,
                     NVIDIA T4 16 GB         ReplicaSet, CronJob, Job
                     AMD MI100 8 GB
  ai-training        NVIDIA A100 80 GB       LLM fine-tuning (Deployment)
                     NVIDIA A100 40 GB       BERT training (StatefulSet)
                     NVIDIA T4 16 GB         Data preprocessing (Job)
  inference-prod     NVIDIA T4 16 GB         Model serving (Deployment)
                     NVIDIA V100 32 GB       Triton server (StatefulSet)
                                             Batch prediction (CronJob)
  data-science       NVIDIA V100 32 GB       Jupyter notebooks (Deployment)
                     NVIDIA A100 80 GB       RAPIDS ETL (Job)
  rendering          AMD MI210 64 GB         Blender rendering (Deployment)
                     AMD MI210 32 GB         Video transcoding (StatefulSet)

Metric layers generated:
  1. Base / input   — accelerator_*, kube_pod_owner, kube_*_owner,
                      kube_pod_container_resource_requests
  2. 5m rules       — acm_rs:{namespace,pod,workload,cluster}:gpu_*:5m
  3. 1d rules       — acm_rs:{namespace,pod,workload,cluster}:gpu_*
                      (with profile / aggregation labels)

Usage (on a machine with promtool):
  python3 generate-gpu-mock-data.py --days 5 -o /tmp/gpu-mock.om
  promtool tsdb create-blocks-from openmetrics /tmp/gpu-mock.om /tmp/gpu-blocks

Generate / regenerate the live PrometheusRule YAML:
  python3 generate-gpu-mock-data.py --live-yaml gpu-base-metrics-mock-prometheusrule.yaml

Import into OpenShift Prometheus:
  ./import-gpu-mock-to-ocp.sh            # uses default 5 days
  ./import-gpu-mock-to-ocp.sh 10         # override to 10 days
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
# Workload definitions — 5 namespaces, 16 pods, diverse GPU types
# ──────────────────────────────────────────────────────────────────────
# GPU model implied by mt (memory_total):
#   85,899,345,920 = A100 80 GB    42,949,672,960 = A100 40 GB
#   68,719,476,736 = MI210 64 GB   34,359,738,368 = V100 32 GB / MI210 32 GB
#   25,769,803,776 = A10   24 GB   17,179,869,184 = T4   16 GB
#    8,589,934,592 = T4    8 GB (MIG) / MI100 8 GB
#
# fmt: off
ALL_PODS = [
    # ── gpu-demo (original namespace — mixed NVIDIA & AMD) ───────
    dict(ns="gpu-demo", pod="gpu-deploy-abcde",       workload="gpu-deploy",       wtype="Deployment",
         gpu_req=2, resource="nvidia.com/gpu", phase=0.10,
         owner_kind="ReplicaSet", owner_name="gpu-deploy-5f8d7f",
         ub=70,  ua=15,  mub=15_032_385_536, mua=2_147_483_648,  mt=25_769_803_776,
         pb=215, pa=25,  tb=72,  ta=5,   sb=1450e6, sa=90e6,  cb=5100e6, ca=120e6),
    dict(ns="gpu-demo", pod="gpu-sts-0",              workload="gpu-sts",          wtype="StatefulSet",
         gpu_req=1, resource="nvidia.com/gpu", phase=0.90,
         owner_kind="StatefulSet", owner_name="gpu-sts",
         ub=58,  ua=12,  mub=9_663_676_416,  mua=1_610_612_736,  mt=17_179_869_184,
         pb=175, pa=20,  tb=68,  ta=4,   sb=1380e6, sa=70e6,  cb=4950e6, ca=100e6),
    dict(ns="gpu-demo", pod="gpu-ds-node1",           workload="gpu-ds",           wtype="DaemonSet",
         gpu_req=1, resource="nvidia.com/gpu", phase=1.60,
         owner_kind="DaemonSet", owner_name="gpu-ds",
         ub=52,  ua=10,  mub=8_589_934_592,  mua=1_288_490_188,  mt=17_179_869_184,
         pb=160, pa=18,  tb=66,  ta=4,   sb=1350e6, sa=65e6,  cb=4900e6, ca=90e6),
    dict(ns="gpu-demo", pod="gpu-rs-xyz",             workload="gpu-rs-standalone", wtype="ReplicaSet",
         gpu_req=1, resource="amd.com/gpu",    phase=2.40,
         owner_kind="ReplicaSet", owner_name="gpu-rs-standalone",
         ub=41,  ua=9,   mub=4_294_967_296,  mua=858_993_459,   mt=8_589_934_592,
         pb=135, pa=16,  tb=62,  ta=3,   sb=1280e6, sa=50e6,  cb=4700e6, ca=85e6),
    dict(ns="gpu-demo", pod="gpu-cj-28930200-abcde",  workload="gpu-cj",           wtype="CronJob",
         gpu_req=1, resource="nvidia.com/gpu", phase=3.10,
         owner_kind="Job", owner_name="gpu-cj-28930200",
         ub=36,  ua=14,  mub=3_758_096_384,  mua=1_181_116_006,  mt=8_589_934_592,
         pb=145, pa=22,  tb=64,  ta=4.5, sb=1300e6, sa=55e6,  cb=4750e6, ca=95e6),
    dict(ns="gpu-demo", pod="gpu-job-12345-xyz",      workload="gpu-job-12345",    wtype="Job",
         gpu_req=1, resource="amd.com/gpu",    phase=3.90,
         owner_kind="Job", owner_name="gpu-job-12345",
         ub=29,  ua=7,   mub=3_006_477_107,  mua=751_619_277,   mt=8_589_934_592,
         pb=120, pa=12,  tb=60,  ta=3,   sb=1220e6, sa=45e6,  cb=4600e6, ca=80e6),

    # ── ai-training (heavy NVIDIA A100 workloads) ────────────────
    dict(ns="ai-training", pod="llm-finetune-abcde",  workload="llm-finetune",     wtype="Deployment",
         gpu_req=4, resource="nvidia.com/gpu", phase=0.30,
         owner_kind="ReplicaSet", owner_name="llm-finetune-7a2c9e",
         ub=88,  ua=8,   mub=72_000_000_000, mua=5_000_000_000,  mt=85_899_345_920,
         pb=310, pa=30,  tb=78,  ta=6,   sb=1530e6, sa=50e6,  cb=5200e6, ca=80e6),
    dict(ns="ai-training", pod="bert-train-0",        workload="bert-train",       wtype="StatefulSet",
         gpu_req=2, resource="nvidia.com/gpu", phase=1.20,
         owner_kind="StatefulSet", owner_name="bert-train",
         ub=65,  ua=12,  mub=28_000_000_000, mua=3_000_000_000,  mt=42_949_672_960,
         pb=250, pa=20,  tb=74,  ta=5,   sb=1480e6, sa=70e6,  cb=5050e6, ca=100e6),
    dict(ns="ai-training", pod="data-preprocess-xyz", workload="data-preprocess",  wtype="Job",
         gpu_req=1, resource="nvidia.com/gpu", phase=2.50,
         owner_kind="Job", owner_name="data-preprocess",
         ub=30,  ua=8,   mub=10_000_000_000, mua=2_000_000_000,  mt=17_179_869_184,
         pb=55,  pa=10,  tb=52,  ta=3,   sb=1200e6, sa=40e6,  cb=4800e6, ca=70e6),

    # ── inference-prod (moderate NVIDIA T4 / V100) ───────────────
    dict(ns="inference-prod", pod="model-server-abcde",        workload="model-server",     wtype="Deployment",
         gpu_req=2, resource="nvidia.com/gpu", phase=0.70,
         owner_kind="ReplicaSet", owner_name="model-server-3b5d8f",
         ub=55,  ua=10,  mub=12_000_000_000, mua=1_500_000_000,  mt=17_179_869_184,
         pb=60,  pa=8,   tb=58,  ta=3,   sb=1290e6, sa=35e6,  cb=4850e6, ca=60e6),
    dict(ns="inference-prod", pod="triton-server-0",           workload="triton-server",    wtype="StatefulSet",
         gpu_req=1, resource="nvidia.com/gpu", phase=1.80,
         owner_kind="StatefulSet", owner_name="triton-server",
         ub=48,  ua=14,  mub=22_000_000_000, mua=4_000_000_000,  mt=34_359_738_368,
         pb=200, pa=25,  tb=70,  ta=5,   sb=1400e6, sa=60e6,  cb=5000e6, ca=90e6),
    dict(ns="inference-prod", pod="batch-predict-cj-100-abcde", workload="batch-predict-cj", wtype="CronJob",
         gpu_req=1, resource="nvidia.com/gpu", phase=3.40,
         owner_kind="Job", owner_name="batch-predict-cj-100",
         ub=40,  ua=18,  mub=8_000_000_000,  mua=3_000_000_000,  mt=17_179_869_184,
         pb=50,  pa=12,  tb=55,  ta=4,   sb=1250e6, sa=45e6,  cb=4750e6, ca=75e6),

    # ── data-science (variable usage — notebooks & ETL) ──────────
    dict(ns="data-science", pod="jupyter-nb-abcde",   workload="jupyter-nb",       wtype="Deployment",
         gpu_req=1, resource="nvidia.com/gpu", phase=0.50,
         owner_kind="ReplicaSet", owner_name="jupyter-nb-9c4f2a",
         ub=25,  ua=12,  mub=8_000_000_000,  mua=4_000_000_000,  mt=34_359_738_368,
         pb=120, pa=30,  tb=50,  ta=8,   sb=1100e6, sa=100e6, cb=4500e6, ca=150e6),
    dict(ns="data-science", pod="rapids-etl-xyz",     workload="rapids-etl",       wtype="Job",
         gpu_req=2, resource="nvidia.com/gpu", phase=2.10,
         owner_kind="Job", owner_name="rapids-etl",
         ub=60,  ua=20,  mub=56_000_000_000, mua=8_000_000_000,  mt=85_899_345_920,
         pb=290, pa=35,  tb=76,  ta=6,   sb=1510e6, sa=55e6,  cb=5150e6, ca=85e6),

    # ── rendering (AMD MI210 GPUs) ───────────────────────────────
    dict(ns="rendering", pod="blender-render-abcde",  workload="blender-render",   wtype="Deployment",
         gpu_req=2, resource="amd.com/gpu",    phase=0.90,
         owner_kind="ReplicaSet", owner_name="blender-render-6d3e1b",
         ub=78,  ua=10,  mub=52_000_000_000, mua=6_000_000_000,  mt=68_719_476_736,
         pb=280, pa=28,  tb=75,  ta=5,   sb=1700e6, sa=80e6,  cb=1600e6, ca=50e6),
    dict(ns="rendering", pod="video-transcode-0",     workload="video-transcode",  wtype="StatefulSet",
         gpu_req=1, resource="amd.com/gpu",    phase=2.70,
         owner_kind="StatefulSet", owner_name="video-transcode",
         ub=50,  ua=15,  mub=20_000_000_000, mua=5_000_000_000,  mt=34_359_738_368,
         pb=180, pa=22,  tb=68,  ta=4,   sb=1650e6, sa=70e6,  cb=1550e6, ca=45e6),
]
# fmt: on

# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _sin(t: int, base: float, amp: float, phase: float) -> float:
    return base + amp * math.sin(t * OMEGA + phase)


def _labels(**kwargs: str) -> str:
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

# Accelerator base-metric → pod_vals key mapping
_ACCEL = [
    ("accelerator_gpu_utilization", "util"),
    ("accelerator_memory_used_bytes", "mem_used"),
    ("accelerator_memory_total_bytes", "mem_total"),
    ("accelerator_power_usage_watts", "power"),
    ("accelerator_temperature_celcius", "temp"),  # spelling matches real exporter
    ("accelerator_sm_clock_hertz", "sm_clk"),
    ("accelerator_memory_clock_hertz", "mem_clk"),
]

# Recording-rule suffix → pod_vals key (None → use constant gpu_req)
_POD_METRICS = [
    ("gpu_request", None),
    ("gpu_usage", "util"),
    ("gpu_memory_used", "mem_used"),
    ("gpu_memory_total", "mem_total"),
    ("gpu_power_usage_watts", "power"),
    ("gpu_temperature_celsius", "temp"),
    ("gpu_sm_clock_hertz", "sm_clk"),
    ("gpu_memory_clock_hertz", "mem_clk"),
]

# Cluster-level 5m metrics: (suffix, aggregation_type)
_CL_SUM = ["gpu_request", "gpu_usage", "gpu_memory_used", "gpu_memory_total", "gpu_power_usage_watts"]
_CL_MAX = ["gpu_temperature_celsius", "gpu_sm_clock_hertz", "gpu_memory_clock_hertz"]

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

    # ── Pre-compute per-pod values ──────────────────────────────
    pod_vals: dict[str, dict[str, list[float]]] = {}
    for p in ALL_PODS:
        ph = p["phase"]
        pod_vals[p["pod"]] = {
            "util": [_sin(t, p["ub"], p["ua"], ph) for t in timestamps],
            "mem_used": [_sin(t, p["mub"], p["mua"], ph) for t in timestamps],
            "mem_total": [float(p["mt"])] * n,
            "power": [_sin(t, p["pb"], p["pa"], ph) for t in timestamps],
            "temp": [_sin(t, p["tb"], p["ta"], ph) for t in timestamps],
            "sm_clk": [_sin(t, p["sb"], p["sa"], ph) for t in timestamps],
            "mem_clk": [_sin(t, p["cb"], p["ca"], ph) for t in timestamps],
        }

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

    # ── kube_pod_container_resource_requests ──
    out.write("# TYPE kube_pod_container_resource_requests gauge\n")
    for p in ALL_PODS:
        ls = _labels(
            cluster=CLUSTER, namespace=p["ns"], pod=p["pod"],
            container="gpu-main", resource=p["resource"], unit="integer",
        )
        _emit(out, "kube_pod_container_resource_requests", ls, timestamps, [float(p["gpu_req"])] * n)

    # ── Accelerator metrics (sinusoidal) ──
    for metric_name, key in _ACCEL:
        out.write(f"# TYPE {metric_name} gauge\n")
        for p in ALL_PODS:
            ls = _labels(cluster=CLUSTER, namespace=p["ns"], pod=p["pod"])
            _emit(out, metric_name, ls, timestamps, pod_vals[p["pod"]][key])

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
            "gpu_request": [float(sum(p["gpu_req"] for p in pods))] * n,
            "gpu_usage": [sum(pod_vals[p["pod"]]["util"][i] for p in pods) for i in range(n)],
            "gpu_utilization": [max(pod_vals[p["pod"]]["util"][i] for p in pods) for i in range(n)],
            "gpu_memory_used": [sum(pod_vals[p["pod"]]["mem_used"][i] for p in pods) for i in range(n)],
            "gpu_memory_total": [sum(pod_vals[p["pod"]]["mem_total"][i] for p in pods) for i in range(n)],
            "gpu_power_usage_watts": [sum(pod_vals[p["pod"]]["power"][i] for p in pods) for i in range(n)],
            "gpu_temperature_celsius": [max(pod_vals[p["pod"]]["temp"][i] for p in pods) for i in range(n)],
            "gpu_sm_clock_hertz": [max(pod_vals[p["pod"]]["sm_clk"][i] for p in pods) for i in range(n)],
            "gpu_memory_clock_hertz": [max(pod_vals[p["pod"]]["mem_clk"][i] for p in pods) for i in range(n)],
        }
        all_ns_5m[ns_name] = ns_5m

    for suffix in all_ns_5m[next(iter(ns_pods))]:
        name = f"acm_rs:namespace:{suffix}:5m"
        out.write(f"# TYPE {name} gauge\n")
        for ns_name in ns_pods:
            ls = _labels(cluster=CLUSTER, namespace=ns_name)
            _emit(out, name, ls, timestamps, all_ns_5m[ns_name][suffix])

    # ── Namespace-level GPU type 5m (max gpu_req per namespace+resource) ──
    ns_gpu_type: dict[tuple[str, str], float] = {}
    for p in ALL_PODS:
        k = (p["ns"], p["resource"])
        ns_gpu_type[k] = max(ns_gpu_type.get(k, 0), float(p["gpu_req"]))

    out.write("# TYPE acm_rs:namespace:gpu_type:5m gauge\n")
    for (ns_name, resource), val in ns_gpu_type.items():
        ls = _labels(cluster=CLUSTER, namespace=ns_name, resource=resource)
        _emit(out, "acm_rs:namespace:gpu_type:5m", ls, timestamps, [val] * n)

    # ── Pod-level 5m ──
    for suffix, key in _POD_METRICS:
        name = f"acm_rs:pod:{suffix}:5m"
        out.write(f"# TYPE {name} gauge\n")
        for p in ALL_PODS:
            ls = _labels(
                cluster=CLUSTER, namespace=p["ns"], pod=p["pod"],
                workload=p["workload"], workload_type=p["wtype"],
            )
            vals = [float(p["gpu_req"])] * n if key is None else pod_vals[p["pod"]][key]
            _emit(out, name, ls, timestamps, vals)

    # ── Workload-level 5m (1 pod per workload in this mock) ──
    for suffix, key in _POD_METRICS:
        name = f"acm_rs:workload:{suffix}:5m"
        out.write(f"# TYPE {name} gauge\n")
        for p in ALL_PODS:
            ls = _labels(
                cluster=CLUSTER, namespace=p["ns"],
                workload=p["workload"], workload_type=p["wtype"],
            )
            vals = [float(p["gpu_req"])] * n if key is None else pod_vals[p["pod"]][key]
            _emit(out, name, ls, timestamps, vals)

    # ── Cluster-level 5m ──
    # Aggregate across all namespaces: sum or max depending on metric
    nss = list(ns_pods.keys())
    cl_5m: dict[str, list[float]] = {}
    for key in _CL_SUM:
        cl_5m[key] = [sum(all_ns_5m[ns][key][i] for ns in nss) for i in range(n)]
    for key in _CL_MAX:
        cl_5m[key] = [max(all_ns_5m[ns][key][i] for ns in nss) for i in range(n)]

    for suffix in _CL_SUM + _CL_MAX:
        name = f"acm_rs:cluster:{suffix}:5m"
        out.write(f"# TYPE {name} gauge\n")
        ls = _labels(cluster=CLUSTER)
        _emit(out, name, ls, timestamps, cl_5m[suffix])

    # ═══════════════════════════════════════════════════════════════
    # 3. RECORDING-RULE OUTPUTS — 1d  (profile="Max OverAll")
    # ═══════════════════════════════════════════════════════════════
    extra = {"profile": "Max OverAll", "aggregation": "1d"}

    # ── Namespace-level GPU type 1d (constant — max_over_time of constant = same) ──
    out.write("# TYPE acm_rs:namespace:gpu_type gauge\n")
    for (ns_name, resource), val in ns_gpu_type.items():
        ls = _labels(cluster=CLUSTER, namespace=ns_name, resource=resource, **extra)
        _emit(out, "acm_rs:namespace:gpu_type", ls, timestamps, [val] * n)

    # ── Namespace-level 1d ──
    for ns_name in ns_pods:
        ns_5m = all_ns_5m[ns_name]
        for suffix, values_5m in ns_5m.items():
            if suffix == "gpu_utilization":
                continue  # no 1d rule for utilization
            name = f"acm_rs:namespace:{suffix}"
            out.write(f"# TYPE {name} gauge\n")
            ls = _labels(cluster=CLUSTER, namespace=ns_name, **extra)
            _emit(out, name, ls, timestamps, _rolling_max(values_5m, window_1d))

        for rec_suffix, src_suffix in [
            ("gpu_recommendation", "gpu_usage"),
            ("gpu_memory_recommendation", "gpu_memory_used"),
        ]:
            name = f"acm_rs:namespace:{rec_suffix}"
            out.write(f"# TYPE {name} gauge\n")
            ls = _labels(cluster=CLUSTER, namespace=ns_name, **extra)
            base = _rolling_max(ns_5m[src_suffix], window_1d)
            _emit(out, name, ls, timestamps, [v * REC_PCT / 100 for v in base])

    # ── Pod-level 1d ──
    for suffix, key in _POD_METRICS:
        name = f"acm_rs:pod:{suffix}"
        out.write(f"# TYPE {name} gauge\n")
        for p in ALL_PODS:
            ls = _labels(
                cluster=CLUSTER, namespace=p["ns"], pod=p["pod"],
                workload=p["workload"], workload_type=p["wtype"], **extra,
            )
            raw = [float(p["gpu_req"])] * n if key is None else pod_vals[p["pod"]][key]
            _emit(out, name, ls, timestamps, _rolling_max(raw, window_1d))

    for rec_suffix, src_key in [
        ("gpu_recommendation", "util"),
        ("gpu_memory_recommendation", "mem_used"),
    ]:
        name = f"acm_rs:pod:{rec_suffix}"
        out.write(f"# TYPE {name} gauge\n")
        for p in ALL_PODS:
            ls = _labels(
                cluster=CLUSTER, namespace=p["ns"], pod=p["pod"],
                workload=p["workload"], workload_type=p["wtype"], **extra,
            )
            base = _rolling_max(pod_vals[p["pod"]][src_key], window_1d)
            _emit(out, name, ls, timestamps, [v * REC_PCT / 100 for v in base])

    # ── Workload-level 1d ──
    for suffix, key in _POD_METRICS:
        name = f"acm_rs:workload:{suffix}"
        out.write(f"# TYPE {name} gauge\n")
        for p in ALL_PODS:
            ls = _labels(
                cluster=CLUSTER, namespace=p["ns"],
                workload=p["workload"], workload_type=p["wtype"], **extra,
            )
            raw = [float(p["gpu_req"])] * n if key is None else pod_vals[p["pod"]][key]
            _emit(out, name, ls, timestamps, _rolling_max(raw, window_1d))

    for rec_suffix, src_key in [
        ("gpu_recommendation", "util"),
        ("gpu_memory_recommendation", "mem_used"),
    ]:
        name = f"acm_rs:workload:{rec_suffix}"
        out.write(f"# TYPE {name} gauge\n")
        for p in ALL_PODS:
            ls = _labels(
                cluster=CLUSTER, namespace=p["ns"],
                workload=p["workload"], workload_type=p["wtype"], **extra,
            )
            base = _rolling_max(pod_vals[p["pod"]][src_key], window_1d)
            _emit(out, name, ls, timestamps, [v * REC_PCT / 100 for v in base])

    # ── Cluster-level 1d ──
    for suffix in _CL_SUM + _CL_MAX:
        name = f"acm_rs:cluster:{suffix}"
        out.write(f"# TYPE {name} gauge\n")
        ls = _labels(cluster=CLUSTER, **extra)
        _emit(out, name, ls, timestamps, _rolling_max(cl_5m[suffix], window_1d))

    for rec_suffix, src_suffix in [
        ("gpu_recommendation", "gpu_usage"),
        ("gpu_memory_recommendation", "gpu_memory_used"),
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
# Synthetic GPU base metrics for ACM GPU right-sizing recording rules.
#
# *** AUTO-GENERATED — do not edit manually ***
# Regenerate:
#   python3 generate-gpu-mock-data.py --live-yaml gpu-base-metrics-mock-prometheusrule.yaml
#
# This manifest creates only INPUT metrics consumed by:
# - operators/multiclusterobservability/controllers/analytics/rightsizing/rs-gpu/prometheusrule.go
#
# Notes:
# - Values follow a 5-hour sinusoidal cycle (period = 18,000 seconds).
# - Recording rules do not backfill historical data; keep this running for 5h to get a full 5h window.
# - Metric spelling intentionally matches exporter input names, including:
#     accelerator_temperature_celcius
#
# Apply:
#   oc apply -f docs/rightsizing/gpu-base-metrics-mock-prometheusrule.yaml
#
# Cleanup:
#   oc -n openshift-monitoring delete prometheusrule acm-gpu-base-metrics-mock
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: acm-gpu-base-metrics-mock
  namespace: openshift-monitoring
  labels:
    prometheus: k8s
    role: alert-rules
spec:
  groups:
"""

# Accelerator params for YAML: (metric_name, base_key, amp_key_or_None, comment)
_ACCEL_YAML = [
    ("accelerator_gpu_utilization", "ub", "ua", "Utilization"),
    ("accelerator_memory_used_bytes", "mub", "mua", "Memory used (bytes)"),
    ("accelerator_memory_total_bytes", "mt", None, "Memory total (bytes)"),
    ("accelerator_power_usage_watts", "pb", "pa", "Power (watts)"),
    ("accelerator_temperature_celcius", "tb", "ta", "Temperature (input metric spelling: celcius)"),
    ("accelerator_sm_clock_hertz", "sb", "sa", "SM clock (hertz)"),
    ("accelerator_memory_clock_hertz", "cb", "ca", "Memory clock (hertz)"),
]


def _yaml_rule(f, record: str, expr: str, labels: dict[str, str]) -> None:
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
        f.write("    - name: acm-gpu-base-mock-owners.rules\n")
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

        # ── Group 2: Request rules ────────────────────────────────
        f.write("\n    - name: acm-gpu-base-mock-requests.rules\n")
        f.write("      interval: 1m\n")
        f.write("      rules:\n")

        for p in ALL_PODS:
            _yaml_rule(f, "kube_pod_container_resource_requests", f"vector({p['gpu_req']})", {
                "cluster": CLUSTER, "namespace": p["ns"], "pod": p["pod"],
                "container": "gpu-main", "resource": p["resource"], "unit": "integer",
            })

        # ── Group 3: Accelerator rules ────────────────────────────
        f.write("\n    - name: acm-gpu-base-mock-accelerator.rules\n")
        f.write("      interval: 1m\n")
        f.write("      rules:\n")

        for metric_name, base_key, amp_key, comment in _ACCEL_YAML:
            f.write(f"        # {comment}\n")
            for p in ALL_PODS:
                if amp_key is None:
                    expr = f"vector({_num(p[base_key])})"
                else:
                    base = _num(p[base_key])
                    amp = _num(p[amp_key])
                    phase = p["phase"]
                    expr = f"{base} + {amp} * sin(vector(time() * {OMEGA_STR} + {phase}))"

                _yaml_rule(f, metric_name, expr, {
                    "cluster": CLUSTER, "namespace": p["ns"], "pod": p["pod"],
                })

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
