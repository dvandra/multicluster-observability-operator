#!/bin/bash
# Copyright (c) Red Hat, Inc.
# Copyright Contributors to the Open Cluster Management project
# Licensed under the Apache License 2.0

# ─────────────────────────────────────────────────────────────────────
# Import CPU/memory right-sizing mock data into an OpenShift Prometheus.
#
# What it does (end-to-end, no local promtool required):
#   1. Generates 5 days of synthetic CPU/memory metrics in OpenMetrics format.
#   2. Copies the file into the Prometheus pod via `oc cp`.
#   3. Runs `promtool tsdb create-blocks-from openmetrics` INSIDE the
#      Prometheus pod (promtool is bundled in every Prometheus image).
#   4. Restarts the Prometheus pod so it loads the new TSDB blocks.
#   5. Applies the live mock PrometheusRule for going-forward data.
#
# Prerequisites:
#   - oc    (logged in to the target cluster with cluster-admin)
#   - python3 (any 3.8+ version — no pip packages needed)
#
# Usage:
#   ./import-cpu-mock-to-ocp.sh            # 5 days (default), openshift-monitoring
#   ./import-cpu-mock-to-ocp.sh 10         # 10 days
#   PROM_NAMESPACE=my-ns PROM_POD=prom-0 ./import-cpu-mock-to-ocp.sh
#
# Environment variables (all optional):
#   PROM_NAMESPACE   Namespace of the Prometheus StatefulSet
#                    (default: openshift-monitoring)
#   PROM_POD         Prometheus pod name
#                    (default: prometheus-k8s-0)
#   PROM_CONTAINER   Container name inside the pod
#                    (default: prometheus)
#   PROM_DATA_DIR    TSDB data directory inside the container
#                    (default: /prometheus)
#   SKIP_RESTART     Set to "true" to skip restarting the Prometheus
#                    pod. Prometheus will pick up new blocks on its
#                    next compaction cycle (~2 min). Avoids any
#                    monitoring gap on production clusters.
#   SKIP_LIVE_MOCK   Set to "true" to skip applying the live
#                    PrometheusRule for going-forward data.
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────
DAYS="${1:-5}"
NS="${PROM_NAMESPACE:-openshift-monitoring}"
POD="${PROM_POD:-prometheus-k8s-0}"
CTR="${PROM_CONTAINER:-prometheus}"
DATA_DIR="${PROM_DATA_DIR:-/prometheus}"
SKIP_RESTART="${SKIP_RESTART:-false}"
SKIP_LIVE="${SKIP_LIVE_MOCK:-false}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GEN_SCRIPT="${SCRIPT_DIR}/generate-cpu-mock-data.py"
MOCK_RULE="${SCRIPT_DIR}/cpu-base-metrics-mock-prometheusrule.yaml"
TMP_FILE="/tmp/cpu-mock-$$.om"

# ── Helpers ──────────────────────────────────────────────────────────
info() { echo "▸ $*"; }
ok() { echo "✅ $*"; }
fail() {
  echo "❌ $*" >&2
  exit 1
}

REMOTE_TMP="${DATA_DIR}/cpu-mock.om" # must be on the writable PVC (rootfs is read-only)

cleanup() {
  rm -f "${TMP_FILE}"
  # Best-effort cleanup inside the pod (ignore errors if pod is gone).
  oc -n "${NS}" exec "${POD}" -c "${CTR}" -- rm -f "${REMOTE_TMP}" 2>/dev/null || true
}
trap cleanup EXIT

# ── Pre-flight checks ───────────────────────────────────────────────
command -v oc >/dev/null 2>&1 || fail "oc CLI not found. Install it and log in first."
command -v python3 >/dev/null 2>&1 || fail "python3 not found. Any 3.8+ version works."
[[ -f ${GEN_SCRIPT} ]] || fail "Generator script not found: ${GEN_SCRIPT}"

info "Verifying cluster access and Prometheus pod (${NS}/${POD})…"
oc -n "${NS}" get pod "${POD}" -o name >/dev/null 2>&1 ||
  fail "Pod ${NS}/${POD} not found. Set PROM_NAMESPACE / PROM_POD."

info "Checking promtool inside the pod…"
oc -n "${NS}" exec "${POD}" -c "${CTR}" -- promtool --version >/dev/null 2>&1 ||
  fail "promtool not available in ${NS}/${POD}:${CTR}."

# ── Step 1: Generate OpenMetrics data ────────────────────────────────
info "Generating ${DAYS} day(s) of CPU/memory mock metrics…"
python3 "${GEN_SCRIPT}" --days "${DAYS}" -o "${TMP_FILE}"
LINE_COUNT=$(wc -l <"${TMP_FILE}" | tr -d ' ')
FILE_SIZE=$(du -h "${TMP_FILE}" | cut -f1)
info "  ${LINE_COUNT} lines, ${FILE_SIZE}"

# ── Step 2: Upload into the Prometheus pod ───────────────────────────
# The container rootfs is read-only; only the PVC at DATA_DIR is writable.
info "Uploading to ${NS}/${POD}:${REMOTE_TMP}…"
oc -n "${NS}" cp "${TMP_FILE}" "${POD}:${REMOTE_TMP}" -c "${CTR}"

# ── Step 3: Build TSDB blocks via promtool ───────────────────────────
info "Building TSDB blocks (this may take a minute)…"
oc -n "${NS}" exec "${POD}" -c "${CTR}" -- \
  env TMPDIR="${DATA_DIR}" \
  promtool tsdb create-blocks-from openmetrics \
  "${REMOTE_TMP}" \
  "${DATA_DIR}"

# ── Step 4: Clean up temp file inside pod ────────────────────────────
oc -n "${NS}" exec "${POD}" -c "${CTR}" -- rm -f "${REMOTE_TMP}"

# ── Step 5: Restart Prometheus to load new blocks ────────────────────
if [[ ${SKIP_RESTART} == "true" ]]; then
  info "Skipping pod restart (SKIP_RESTART=true)."
  info "Prometheus will discover new blocks on its next compaction cycle (~2 min)."
else
  info "Restarting Prometheus pod to load new blocks…"
  oc -n "${NS}" delete pod "${POD}" --wait=false

  # Wait for the new pod to become Ready.
  info "Waiting for new ${POD} to become Ready…"
  oc -n "${NS}" wait pod "${POD}" --for=condition=Ready --timeout=120s 2>/dev/null || {
    info "(pod still starting — it may take another moment)"
  }
fi

# ── Step 6: Apply live mock for going-forward data ───────────────────
if [[ ${SKIP_LIVE} != "true" && -f ${MOCK_RULE} ]]; then
  info "Applying live mock PrometheusRule for going-forward data…"
  oc apply -f "${MOCK_RULE}"
fi

# ── Done ─────────────────────────────────────────────────────────────
ok "CPU/memory right-sizing mock data (${DAYS}d history) imported into ${NS}/${POD}."
echo "   Grafana dashboards should show data within 1–2 minutes."
