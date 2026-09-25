---
name: mco-impact-map
description: >-
  Produce a repository impact map for MCO (multicluster-observability-operator).
  Use when starting a new feature, analyzing a change request, or when the user
  says "plan", "analyze", "impact map", or "what needs to change" for MCO.
---
# MCO Repository Impact Map

You analyze the MCO monorepo and produce a grounded impact map before any code is written.

## MCO-Specific Analysis Steps

1. **Read the requirement** — ticket, description, or feature spec
2. **Identify the architecture** — does this touch Legacy or MCOA? (see AGENTS.md Section 1.2)
   - Legacy: `operators/endpointmetrics/`, `collectors/metrics/`, ManifestWorks, metrics-allowlist
   - MCOA: addon-framework, PrometheusAgent, ScrapeConfig, PrometheusRule
3. **Identify affected components** in this monorepo:
   - `operators/multiclusterobservability/` — Hub MCO operator (controllers, API types, manifests)
   - `operators/endpointmetrics/` — Legacy endpoint operator
   - `collectors/metrics/` — Legacy metrics collector
   - `proxy/` — RBAC query proxy
   - `loaders/dashboards/` — Grafana dashboard loader
   - `operators/pkg/` — Shared packages across operators
4. **Scan for real paths and symbols**:
   - Search `operators/multiclusterobservability/api/` for CRD types
   - Search `operators/multiclusterobservability/controllers/` for reconcilers
   - Search `operators/multiclusterobservability/manifests/` for kustomize bases
   - Grep for function signatures, type definitions, existing patterns
5. **Check cross-repo impact** — does this affect MCOA (multicluster-observability-addon)?
6. **Produce the impact map** using `templates/impact-map-template.md`

## Key Directories to Search

| What | Where |
|------|-------|
| CRD types (v1beta1, v1beta2) | `operators/multiclusterobservability/api/` |
| Hub controllers | `operators/multiclusterobservability/controllers/` |
| Endpoint controllers | `operators/endpointmetrics/controllers/` |
| Shared operator packages | `operators/pkg/` |
| Manifests/kustomize | `operators/multiclusterobservability/manifests/` |
| Metrics allowlist | `operators/multiclusterobservability/manifests/base/config/metrics_allowlist.yaml` |
| E2E tests | `tests/pkg/tests/` |
| Unit tests | Colocated `*_test.go` files |

## Rules

- NEVER guess paths. Verify every file path by searching.
- ALWAYS identify Legacy vs MCOA architecture impact.
- ALWAYS check `operators/pkg/` for shared code that might be affected.
- Flag hub-self-management constraints if the change touches hub metrics (AGENTS.md Section 1.3).
- Note if the change requires Containerfile label updates.
- Save to `docs/impact-maps/<feature-slug>.md`
- **STOP for human review** before proceeding.

## Context Exclusions

Skip: `vendor/`, `tmp/`, `.git/`, `bin/`, `coverage/`.
