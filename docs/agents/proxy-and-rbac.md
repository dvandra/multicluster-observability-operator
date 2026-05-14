# Proxy and RBAC

> RBAC-aware Thanos query proxy that scopes metric access per managed cluster. For the main operator and CR API, see [mco-operator-core.md](mco-operator-core.md). For the right-sizing API, see [rightsizing-api.md](rightsizing-api.md).

## Key Entry Points (verified from actual code)

- `proxy/cmd/main.go` - Process entry: wires k8s + OCM cluster clients, rbac.NewAccessReviewer, ManagedCluster informer, TLS transport, proxy.NewProxy, HTTP server on 0.0.0.0:3002
- `proxy/pkg/proxy/proxy.go` - Proxy, NewProxy, ServeHTTP: reverse proxy to --metrics-server; auth pre-check; path rewrite under /api/metrics/v1/default; invokes metricquery.Modifier
- `proxy/pkg/proxy/tls.go` - TLSOptions, NewTransport, reloadingTransport: mTLS client with hot reload
- `proxy/pkg/metricquery/modifier.go` - Modifier, Modify: RBAC enforcement via GetMetricsAccess(token); rewrites query and match[] via PromQL rewrite
- `proxy/pkg/metricquery/filter.go` - NamespaceFilter: walks PromQL AST for cluster matchers; injects namespace label
- `proxy/pkg/rewrite/rewrite_cluster.go` - InjectClusterLabels: injects cluster label on all selectors; uses name instead of cluster for acm_managed_cluster_labels
- `proxy/pkg/rewrite/rewrite.go` - InjectLabels: generic AST walk appending label matchers
- `proxy/pkg/config/config.go` - Constants, synthetic metric acm_label_names
- `proxy/pkg/informer/informer.go` - ManagedClusterInformer: watches ManagedCluster + allowlist ConfigMap; maintains in-memory cluster/label state
- `proxy/pkg/cache/user_project.go` - UserProjectInfo: token-keyed cache of OpenShift projects (24h TTL)
- `proxy/pkg/health/health.go` - /healthz (always OK), /readyz (informer synced + HEAD to metrics server)

## Key pattern: RBAC scoping

1. Identity: X-Forwarded-Access-Token or Authorization Bearer
2. Metrics ACLs via rbac-api-utils GetMetricsAccess
3. Legacy namespace bridge: OpenShift projects matching cluster names
4. PromQL rewrite: InjectClusterLabels + NamespaceFilter
5. Admin bypass: canAccessAll skips rewrite

## Key pattern: Synthetic label metric

acm_label_names does NOT exist upstream. For series/label endpoints, handleManagedClusterLabelQuery returns JSON from ManagedClusterInformer.

## Gotchas (verified)

- Same Go module as repo root (NOT separate go.mod)
- OAuth-proxy sidecar is the real TLS edge; direct port 8080 access needs manual headers
- Pre-check failures return 200 with empty matrix (masks as "no metrics")
- No managed clusters = hard fail with empty-matrix response
- TLS hot reload via polling (no pod restart needed)
- Content-Length uses len([]rune(rawQuery)) which can diverge from byte length for non-ASCII
- Only query and match[] params are rewritten; other endpoints pass through with path prefixing only
- GET query/query_range/series converted to POST before forwarding

## Dependencies

- Observatorium hub metrics API (mTLS upstream)
- prometheus/prometheus promql/parser for AST walks
- OCM ManagedCluster informer
- OpenShift API (Project + User)
- rbac-api-utils AccessReviewer
- golang-jwt/jwt for unverified subject extraction

## Links

- [mco-operator-core.md](mco-operator-core.md), [rightsizing-api.md](rightsizing-api.md), [ARCHITECTURE.md](../ARCHITECTURE.md)
