# Right-Sizing MCP Demo on OCP

This preview provides a small **MCP-over-HTTP** service that reads MCO right-sizing recording rules from hub Prometheus/Thanos and exposes three MCP tools:

- `get_top_rightsizing_targets`
- `explain_rightsizing_target`
- `get_gpu_rightsizing_insights`

The service is intended for a **quick demo only** (not production hardening).

## What this demo reads

The service queries existing `acm_rs:*` recording rules, including:

- `acm_rs:workload:cpu_request`, `acm_rs:workload:cpu_usage`, `acm_rs:workload:cpu_recommendation`
- `acm_rs:workload:memory_request`, `acm_rs:workload:memory_usage`, `acm_rs:workload:memory_recommendation`
- `acm_rs:workload:gpu_request`, `acm_rs:workload:gpu_usage`, `acm_rs:workload:gpu_recommendation`
- and optional GPU details (`gpu_memory_*`, `gpu_power_usage_watts`, `gpu_temperature_celsius`)

## Prerequisites

1. OCP hub cluster with MCO right-sizing enabled.
2. Right-sizing recording rules present in `openshift-monitoring`.
3. You can build and push an image to a registry your cluster can pull from.

Quick checks:

```bash
oc -n openshift-monitoring get prometheusrule acm-rs-workload-prometheus-rules
oc -n openshift-monitoring get prometheusrule acm-rs-gpu-prometheus-rules
```

## 1) Build and push the image

From repo root:

```bash
export IMAGE=quay.io/<your-org>/mco-rightsizing-mcp-demo:$(date +%Y%m%d%H%M%S)
podman build -f dev-previews/rightsizing-mcp/Dockerfile -t "${IMAGE}" .
podman push "${IMAGE}"
```

If you use Docker, replace `podman` with `docker`.

## 2) Deploy to OCP

```bash
oc apply -k dev-previews/rightsizing-mcp/manifests
oc -n mco-rightsizing-mcp-demo set image deployment/mco-rightsizing-mcp mco-rightsizing-mcp="${IMAGE}"
oc -n mco-rightsizing-mcp-demo rollout status deployment/mco-rightsizing-mcp
```

The deployment uses:

- ServiceAccount `mco-rightsizing-mcp`
- ClusterRoleBinding to `cluster-monitoring-view` (read-only monitoring access)
- Service + Route for external access
- `PROM_INSECURE_SKIP_VERIFY=true` by default for demo convenience

## 3) Smoke test

```bash
export MCP_HOST=$(oc -n mco-rightsizing-mcp-demo get route mco-rightsizing-mcp -o jsonpath='{.spec.host}')
curl -sk "https://${MCP_HOST}/healthz"
```

Expected output: `ok`

## 4) MCP protocol checks with curl

### Initialize

```bash
curl -sk "https://${MCP_HOST}/mcp" \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"initialize",
    "params":{
      "protocolVersion":"2024-11-05",
      "clientInfo":{"name":"manual-curl","version":"0.1.0"},
      "capabilities":{}
    }
  }' | jq
```

### List tools

```bash
curl -sk "https://${MCP_HOST}/mcp" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' | jq
```

### Call: top CPU targets

```bash
curl -sk "https://${MCP_HOST}/mcp" \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc":"2.0",
    "id":3,
    "method":"tools/call",
    "params":{
      "name":"get_top_rightsizing_targets",
      "arguments":{"resource":"cpu","limit":5}
    }
  }' | jq -r '.result.content[0].text'
```

### Call: explain one workload

```bash
curl -sk "https://${MCP_HOST}/mcp" \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc":"2.0",
    "id":4,
    "method":"tools/call",
    "params":{
      "name":"explain_rightsizing_target",
      "arguments":{
        "resource":"memory",
        "namespace":"<namespace>",
        "workload":"<workload>",
        "cluster":"<cluster-optional>"
      }
    }
  }' | jq -r '.result.content[0].text'
```

### Call: GPU insights

```bash
curl -sk "https://${MCP_HOST}/mcp" \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc":"2.0",
    "id":5,
    "method":"tools/call",
    "params":{
      "name":"get_gpu_rightsizing_insights",
      "arguments":{"limit":5}
    }
  }' | jq -r '.result.content[0].text'
```

## 5) Connect from an MCP client

Use your MCP client's **HTTP transport** mode and point it to:

- URL: `https://<route-host>/mcp`
- Method: `POST`
- Content type: `application/json`

If your client supports custom headers, you can add a bearer token by setting `MCP_API_KEY` in the deployment and passing `Authorization: Bearer <token>`.

## Troubleshooting

- `403` from Prometheus query:
  - Verify the service account has monitoring read access.
  - Check the ClusterRoleBinding in `manifests/clusterrolebinding.yaml`.
- Empty tool output:
  - Verify right-sizing rules exist and are evaluating.
  - Check raw metric availability in Prometheus for `acm_rs:workload:*`.
- TLS errors:
  - The deployment defaults `PROM_INSECURE_SKIP_VERIFY=true` for demo speed.
  - For stricter TLS verification, set it to `false` and provide a CA bundle trusted by the target metrics endpoint.

## Cleanup

```bash
oc delete -k dev-previews/rightsizing-mcp/manifests
```
