// Copyright (c) Red Hat, Inc.
// Copyright Contributors to the Open Cluster Management project
// Licensed under the Apache License 2.0

package main

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"os"
	"sort"
	"strconv"
	"strings"
	"time"
)

const (
	defaultListenAddr    = ":8080"
	defaultPromURL       = "https://thanos-querier.openshift-monitoring.svc:9091"
	defaultPromTokenFile = "/var/run/secrets/kubernetes.io/serviceaccount/token"
	defaultPromCAFile    = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
	defaultLogLevel      = "info"
	mcpProtocolVersion   = "2024-11-05"
)

const (
	promMetricWorkloadCPURequest              = "acm_rs:workload:cpu_request"
	promMetricWorkloadCPULimit                = "acm_rs:workload:cpu_limit"
	promMetricWorkloadCPUUsage                = "acm_rs:workload:cpu_usage"
	promMetricWorkloadCPURecommendation       = "acm_rs:workload:cpu_recommendation"
	promMetricWorkloadMemoryRequest           = "acm_rs:workload:memory_request"
	promMetricWorkloadMemoryLimit             = "acm_rs:workload:memory_limit"
	promMetricWorkloadMemoryUsage             = "acm_rs:workload:memory_usage"
	promMetricWorkloadMemoryRecommendation    = "acm_rs:workload:memory_recommendation"
	promMetricWorkloadGPURequest              = "acm_rs:workload:gpu_request"
	promMetricWorkloadGPUUsage                = "acm_rs:workload:gpu_usage"
	promMetricWorkloadGPURecommendation       = "acm_rs:workload:gpu_recommendation"
	promMetricWorkloadGPUMemoryUsed           = "acm_rs:workload:gpu_memory_used"
	promMetricWorkloadGPUMemoryRecommendation = "acm_rs:workload:gpu_memory_recommendation"
	promMetricWorkloadGPUMemoryTotal          = "acm_rs:workload:gpu_memory_total"
	promMetricWorkloadGPUPowerWatts           = "acm_rs:workload:gpu_power_usage_watts"
	promMetricWorkloadGPUTemperatureC         = "acm_rs:workload:gpu_temperature_celsius"
)

type app struct {
	logger    *slog.Logger
	prom      *promClient
	mcpAPIKey string
}

type resourceMetrics struct {
	requestMetric        string
	limitMetric          string
	usageMetric          string
	recommendationMetric string
	unit                 string
}

var resources = map[string]resourceMetrics{
	"cpu": {
		requestMetric:        promMetricWorkloadCPURequest,
		limitMetric:          promMetricWorkloadCPULimit,
		usageMetric:          promMetricWorkloadCPUUsage,
		recommendationMetric: promMetricWorkloadCPURecommendation,
		unit:                 "cores",
	},
	"memory": {
		requestMetric:        promMetricWorkloadMemoryRequest,
		limitMetric:          promMetricWorkloadMemoryLimit,
		usageMetric:          promMetricWorkloadMemoryUsage,
		recommendationMetric: promMetricWorkloadMemoryRecommendation,
		unit:                 "bytes",
	},
	"gpu": {
		requestMetric:        promMetricWorkloadGPURequest,
		usageMetric:          promMetricWorkloadGPUUsage,
		recommendationMetric: promMetricWorkloadGPURecommendation,
		unit:                 "gpus",
	},
}

type promClient struct {
	baseURL     *url.URL
	bearerToken string
	httpClient  *http.Client
}

type promQueryResponse struct {
	Status    string `json:"status"`
	ErrorType string `json:"errorType"`
	Error     string `json:"error"`
	Data      struct {
		ResultType string            `json:"resultType"`
		Result     []promQueryResult `json:"result"`
	} `json:"data"`
}

type promQueryResult struct {
	Metric map[string]string `json:"metric"`
	Value  []any             `json:"value"`
}

type promSample struct {
	Labels map[string]string
	Value  float64
}

type jsonRPCRequest struct {
	JSONRPC string           `json:"jsonrpc"`
	ID      *json.RawMessage `json:"id,omitempty"`
	Method  string           `json:"method"`
	Params  json.RawMessage  `json:"params,omitempty"`
}

type jsonRPCResponse struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      json.RawMessage `json:"id"`
	Result  any             `json:"result,omitempty"`
	Error   *jsonRPCError   `json:"error,omitempty"`
}

type jsonRPCError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

type toolCallParams struct {
	Name      string         `json:"name"`
	Arguments map[string]any `json:"arguments"`
}

type topTargetsArgs struct {
	Resource  string
	Limit     int
	Cluster   string
	Namespace string
}

type explainTargetArgs struct {
	Resource     string
	Cluster      string
	Namespace    string
	Workload     string
	WorkloadType string
}

type gpuInsightsArgs struct {
	Limit     int
	Cluster   string
	Namespace string
	Workload  string
}

type targetDetail struct {
	Cluster        string
	Namespace      string
	Workload       string
	WorkloadType   string
	Request        float64
	Limit          float64
	Usage          float64
	Recommendation float64
	Savings        float64
	Confidence     string
}

type gpuDetail struct {
	targetDetail
	MemoryUsed           float64
	MemoryRecommendation float64
	MemoryTotal          float64
	PowerWatts           float64
	TemperatureCelsius   float64
}

func main() {
	logger := newLogger(getEnvOrDefault("LOG_LEVEL", defaultLogLevel))

	prom, err := newPromClientFromEnv()
	if err != nil {
		logger.Error("failed to initialize Prometheus client", "error", err)
		os.Exit(1)
	}

	a := &app{
		logger:    logger,
		prom:      prom,
		mcpAPIKey: strings.TrimSpace(os.Getenv("MCP_API_KEY")),
	}

	listenAddr := getEnvOrDefault("LISTEN_ADDR", defaultListenAddr)
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", a.handleHealthz)
	mux.HandleFunc("/mcp", a.handleMCP)
	mux.HandleFunc("/", a.handleRoot)

	server := &http.Server{
		Addr:              listenAddr,
		Handler:           mux,
		ReadHeaderTimeout: 10 * time.Second,
	}

	logger.Info(
		"starting right-sizing MCP demo server",
		"listen_addr",
		listenAddr,
		"prom_url",
		prom.baseURL.String(),
		"auth_enabled",
		a.mcpAPIKey != "",
	)

	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		logger.Error("server stopped unexpectedly", "error", err)
		os.Exit(1)
	}
}

func (a *app) handleRoot(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/" {
		http.NotFound(w, r)
		return
	}

	_, _ = io.WriteString(
		w,
		"mco-rightsizing-mcp demo is running. POST JSON-RPC requests to /mcp and probe /healthz.\n",
	)
}

func (a *app) handleHealthz(w http.ResponseWriter, _ *http.Request) {
	w.WriteHeader(http.StatusOK)
	_, _ = io.WriteString(w, "ok\n")
}

func (a *app) handleMCP(w http.ResponseWriter, r *http.Request) {
	applyCORSHeaders(w)

	if r.Method == http.MethodOptions {
		w.WriteHeader(http.StatusNoContent)
		return
	}

	if r.Method != http.MethodPost {
		http.Error(w, "only POST is supported", http.StatusMethodNotAllowed)
		return
	}

	if a.mcpAPIKey != "" && !matchesBearerToken(r.Header.Get("Authorization"), a.mcpAPIKey) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}

	var req jsonRPCRequest
	if err := json.NewDecoder(io.LimitReader(r.Body, 1<<20)).Decode(&req); err != nil {
		a.writeJSONRPCError(w, req, -32700, fmt.Sprintf("invalid JSON payload: %v", err))
		return
	}

	if req.JSONRPC != "2.0" || req.Method == "" {
		a.writeJSONRPCError(w, req, -32600, "invalid JSON-RPC request")
		return
	}

	result, rpcErr, respond := a.processRequest(r.Context(), req)
	if !respond {
		w.WriteHeader(http.StatusNoContent)
		return
	}

	responseID := json.RawMessage("null")
	if req.ID != nil {
		responseID = *req.ID
	}

	resp := jsonRPCResponse{
		JSONRPC: "2.0",
		ID:      responseID,
		Result:  result,
		Error:   rpcErr,
	}

	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(resp); err != nil {
		a.logger.Error("failed to encode JSON-RPC response", "error", err)
	}
}

func (a *app) processRequest(ctx context.Context, req jsonRPCRequest) (any, *jsonRPCError, bool) {
	switch req.Method {
	case "initialize":
		return map[string]any{
			"protocolVersion": mcpProtocolVersion,
			"capabilities": map[string]any{
				"tools": map[string]any{},
			},
			"serverInfo": map[string]any{
				"name":    "mco-rightsizing-mcp-demo",
				"version": "0.1.0",
			},
		}, nil, req.ID != nil
	case "notifications/initialized":
		return nil, nil, false
	case "ping":
		return map[string]any{}, nil, req.ID != nil
	case "tools/list":
		return map[string]any{
			"tools": mcpTools(),
		}, nil, req.ID != nil
	case "tools/call":
		if req.ID == nil {
			return nil, nil, false
		}

		var params toolCallParams
		if err := json.Unmarshal(req.Params, &params); err != nil {
			return nil, &jsonRPCError{
				Code:    -32602,
				Message: fmt.Sprintf("invalid tools/call params: %v", err),
			}, true
		}

		if params.Arguments == nil {
			params.Arguments = map[string]any{}
		}

		output, err := a.executeTool(ctx, params.Name, params.Arguments)
		if err != nil {
			return map[string]any{
				"isError": true,
				"content": []map[string]string{
					{
						"type": "text",
						"text": err.Error(),
					},
				},
			}, nil, true
		}

		return map[string]any{
			"content": []map[string]string{
				{
					"type": "text",
					"text": output,
				},
			},
		}, nil, true
	default:
		if req.ID == nil {
			return nil, nil, false
		}

		return nil, &jsonRPCError{
			Code:    -32601,
			Message: fmt.Sprintf("method %q is not supported", req.Method),
		}, true
	}
}

func (a *app) executeTool(ctx context.Context, name string, args map[string]any) (string, error) {
	switch name {
	case "get_top_rightsizing_targets":
		return a.toolGetTopRightsizingTargets(ctx, args)
	case "explain_rightsizing_target":
		return a.toolExplainRightsizingTarget(ctx, args)
	case "get_gpu_rightsizing_insights":
		return a.toolGetGPURightsizingInsights(ctx, args)
	default:
		return "", fmt.Errorf("unknown tool %q", name)
	}
}

func (a *app) toolGetTopRightsizingTargets(ctx context.Context, rawArgs map[string]any) (string, error) {
	args, err := parseTopTargetsArgs(rawArgs)
	if err != nil {
		return "", err
	}

	cfg := resources[args.Resource]
	selector := buildSelector(map[string]string{
		"cluster":   args.Cluster,
		"namespace": args.Namespace,
	})

	savingsExpr := fmt.Sprintf(
		"topk(%d, clamp_min((%s%s) - (%s%s), 0))",
		args.Limit,
		cfg.requestMetric,
		selector,
		cfg.recommendationMetric,
		selector,
	)

	topSavings, err := a.prom.Query(ctx, savingsExpr)
	if err != nil {
		return "", fmt.Errorf("failed to query top right-sizing targets: %w", err)
	}

	if len(topSavings) == 0 {
		return "No right-sizing series found for the selected filters.", nil
	}

	details := make([]targetDetail, 0, len(topSavings))
	for _, sample := range topSavings {
		identity := labelsForWorkloadSeries(sample.Labels)

		requestValue, err := a.queryRequiredValue(ctx, cfg.requestMetric, identity)
		if err != nil {
			continue
		}
		usageValue, err := a.queryRequiredValue(ctx, cfg.usageMetric, identity)
		if err != nil {
			continue
		}
		recommendationValue, err := a.queryRequiredValue(ctx, cfg.recommendationMetric, identity)
		if err != nil {
			continue
		}

		limitValue := 0.0
		if cfg.limitMetric != "" {
			if value, ok := a.queryOptionalValue(ctx, cfg.limitMetric, identity); ok {
				limitValue = value
			}
		}

		confidence, _ := computeConfidence(requestValue, usageValue)

		details = append(details, targetDetail{
			Cluster:        sample.Labels["cluster"],
			Namespace:      sample.Labels["namespace"],
			Workload:       sample.Labels["workload"],
			WorkloadType:   sample.Labels["workload_type"],
			Request:        requestValue,
			Limit:          limitValue,
			Usage:          usageValue,
			Recommendation: recommendationValue,
			Savings:        sample.Value,
			Confidence:     confidence,
		})
	}

	if len(details) == 0 {
		return "Right-sizing series were found, but no complete workload records were available.", nil
	}

	var builder strings.Builder
	fmt.Fprintf(
		&builder,
		"Top %d %s right-sizing targets based on `request - recommendation`.\n\n",
		len(details),
		args.Resource,
	)
	builder.WriteString(
		"| Cluster | Namespace | Workload | Type | Request | Usage | Recommendation | Potential Savings | Confidence |\n",
	)
	builder.WriteString(
		"| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n",
	)

	for _, detail := range details {
		fmt.Fprintf(
			&builder,
			"| %s | %s | %s | %s | %s | %s | %s | %s | %s |\n",
			emptyDash(detail.Cluster),
			emptyDash(detail.Namespace),
			emptyDash(detail.Workload),
			emptyDash(detail.WorkloadType),
			formatResourceValue(args.Resource, detail.Request),
			formatResourceValue(args.Resource, detail.Usage),
			formatResourceValue(args.Resource, detail.Recommendation),
			formatResourceValue(args.Resource, detail.Savings),
			detail.Confidence,
		)
	}

	builder.WriteString(
		"\nRecommendations come from `acm_rs:*_recommendation`, derived from max 1-day usage multiplied by recommendation percentage.\n",
	)
	return builder.String(), nil
}

func (a *app) toolExplainRightsizingTarget(ctx context.Context, rawArgs map[string]any) (string, error) {
	args, err := parseExplainTargetArgs(rawArgs)
	if err != nil {
		return "", err
	}

	cfg := resources[args.Resource]
	selectorLabels := map[string]string{
		"cluster":       args.Cluster,
		"namespace":     args.Namespace,
		"workload":      args.Workload,
		"workload_type": args.WorkloadType,
	}

	requestValue, err := a.queryRequiredValue(ctx, cfg.requestMetric, selectorLabels)
	if err != nil {
		return "", fmt.Errorf("failed to query request for target: %w", err)
	}

	usageValue, err := a.queryRequiredValue(ctx, cfg.usageMetric, selectorLabels)
	if err != nil {
		return "", fmt.Errorf("failed to query usage for target: %w", err)
	}

	recommendationValue, err := a.queryRequiredValue(ctx, cfg.recommendationMetric, selectorLabels)
	if err != nil {
		return "", fmt.Errorf("failed to query recommendation for target: %w", err)
	}

	limitValue := 0.0
	limitFound := false
	if cfg.limitMetric != "" {
		limitValue, limitFound = a.queryOptionalValue(ctx, cfg.limitMetric, selectorLabels)
	}

	savings := requestValue - recommendationValue
	if savings < 0 {
		savings = 0
	}

	savingsPct := 0.0
	if requestValue > 0 {
		savingsPct = (savings / requestValue) * 100
	}

	confidence, reason := computeConfidence(requestValue, usageValue)

	var builder strings.Builder
	builder.WriteString("Right-sizing explanation for selected workload:\n\n")
	fmt.Fprintf(&builder, "- Resource: `%s`\n", args.Resource)
	fmt.Fprintf(&builder, "- Cluster: `%s`\n", emptyDash(args.Cluster))
	fmt.Fprintf(&builder, "- Namespace: `%s`\n", args.Namespace)
	fmt.Fprintf(&builder, "- Workload: `%s`\n", args.Workload)
	fmt.Fprintf(&builder, "- Workload type: `%s`\n", emptyDash(args.WorkloadType))
	fmt.Fprintf(&builder, "- Request: `%s`\n", formatResourceValue(args.Resource, requestValue))
	if limitFound {
		fmt.Fprintf(&builder, "- Limit: `%s`\n", formatResourceValue(args.Resource, limitValue))
	}
	fmt.Fprintf(&builder, "- Observed usage (1d max): `%s`\n", formatResourceValue(args.Resource, usageValue))
	fmt.Fprintf(&builder, "- Recommendation: `%s`\n", formatResourceValue(args.Resource, recommendationValue))
	fmt.Fprintf(
		&builder,
		"- Potential savings: `%s` (%.1f%% of request)\n",
		formatResourceValue(args.Resource, savings),
		savingsPct,
	)
	fmt.Fprintf(&builder, "- Confidence: `%s` (%s)\n", confidence, reason)

	if args.Resource == "gpu" {
		if value, ok := a.queryOptionalValue(ctx, promMetricWorkloadGPUMemoryUsed, selectorLabels); ok {
			fmt.Fprintf(&builder, "- GPU memory used: `%s`\n", formatBytes(value))
		}
		if value, ok := a.queryOptionalValue(ctx, promMetricWorkloadGPUMemoryRecommendation, selectorLabels); ok {
			fmt.Fprintf(&builder, "- GPU memory recommendation: `%s`\n", formatBytes(value))
		}
		if value, ok := a.queryOptionalValue(ctx, promMetricWorkloadGPUMemoryTotal, selectorLabels); ok {
			fmt.Fprintf(&builder, "- GPU memory total: `%s`\n", formatBytes(value))
		}
		if value, ok := a.queryOptionalValue(ctx, promMetricWorkloadGPUPowerWatts, selectorLabels); ok {
			fmt.Fprintf(&builder, "- GPU power usage: `%.2f W`\n", value)
		}
		if value, ok := a.queryOptionalValue(ctx, promMetricWorkloadGPUTemperatureC, selectorLabels); ok {
			fmt.Fprintf(&builder, "- GPU temperature: `%.2f C`\n", value)
		}
	}

	return builder.String(), nil
}

func (a *app) toolGetGPURightsizingInsights(ctx context.Context, rawArgs map[string]any) (string, error) {
	args, err := parseGPUInsightsArgs(rawArgs)
	if err != nil {
		return "", err
	}

	if args.Workload != "" {
		// Reuse the detailed target explanation when a single workload is requested.
		return a.toolExplainRightsizingTarget(ctx, map[string]any{
			"resource":  "gpu",
			"cluster":   args.Cluster,
			"namespace": args.Namespace,
			"workload":  args.Workload,
		})
	}

	selector := buildSelector(map[string]string{
		"cluster":   args.Cluster,
		"namespace": args.Namespace,
	})

	topExpr := fmt.Sprintf(
		"topk(%d, clamp_min((%s%s) - (%s%s), 0))",
		args.Limit,
		promMetricWorkloadGPURequest,
		selector,
		promMetricWorkloadGPURecommendation,
		selector,
	)

	topSamples, err := a.prom.Query(ctx, topExpr)
	if err != nil {
		return "", fmt.Errorf("failed to query gpu insights: %w", err)
	}

	if len(topSamples) == 0 {
		return "No GPU right-sizing series found for the selected filters.", nil
	}

	details := make([]gpuDetail, 0, len(topSamples))
	for _, sample := range topSamples {
		identity := labelsForWorkloadSeries(sample.Labels)

		requestValue, err := a.queryRequiredValue(ctx, promMetricWorkloadGPURequest, identity)
		if err != nil {
			continue
		}
		usageValue, err := a.queryRequiredValue(ctx, promMetricWorkloadGPUUsage, identity)
		if err != nil {
			continue
		}
		recommendationValue, err := a.queryRequiredValue(ctx, promMetricWorkloadGPURecommendation, identity)
		if err != nil {
			continue
		}

		confidence, _ := computeConfidence(requestValue, usageValue)
		detail := gpuDetail{
			targetDetail: targetDetail{
				Cluster:        sample.Labels["cluster"],
				Namespace:      sample.Labels["namespace"],
				Workload:       sample.Labels["workload"],
				WorkloadType:   sample.Labels["workload_type"],
				Request:        requestValue,
				Usage:          usageValue,
				Recommendation: recommendationValue,
				Savings:        sample.Value,
				Confidence:     confidence,
			},
		}

		if value, ok := a.queryOptionalValue(ctx, promMetricWorkloadGPUMemoryUsed, identity); ok {
			detail.MemoryUsed = value
		}
		if value, ok := a.queryOptionalValue(ctx, promMetricWorkloadGPUMemoryRecommendation, identity); ok {
			detail.MemoryRecommendation = value
		}
		if value, ok := a.queryOptionalValue(ctx, promMetricWorkloadGPUMemoryTotal, identity); ok {
			detail.MemoryTotal = value
		}
		if value, ok := a.queryOptionalValue(ctx, promMetricWorkloadGPUPowerWatts, identity); ok {
			detail.PowerWatts = value
		}
		if value, ok := a.queryOptionalValue(ctx, promMetricWorkloadGPUTemperatureC, identity); ok {
			detail.TemperatureCelsius = value
		}

		details = append(details, detail)
	}

	if len(details) == 0 {
		return "GPU series were found, but no complete workload records were available.", nil
	}

	var builder strings.Builder
	fmt.Fprintf(&builder, "Top %d GPU right-sizing insights.\n\n", len(details))
	builder.WriteString(
		"| Cluster | Namespace | Workload | Type | GPU Request | GPU Usage | GPU Recommendation | GPU Savings | Memory Used | Memory Recommendation | Power | Temperature |\n",
	)
	builder.WriteString(
		"| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n",
	)

	for _, detail := range details {
		fmt.Fprintf(
			&builder,
			"| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %.2f W | %.2f C |\n",
			emptyDash(detail.Cluster),
			emptyDash(detail.Namespace),
			emptyDash(detail.Workload),
			emptyDash(detail.WorkloadType),
			formatResourceValue("gpu", detail.Request),
			formatResourceValue("gpu", detail.Usage),
			formatResourceValue("gpu", detail.Recommendation),
			formatResourceValue("gpu", detail.Savings),
			formatBytes(detail.MemoryUsed),
			formatBytes(detail.MemoryRecommendation),
			detail.PowerWatts,
			detail.TemperatureCelsius,
		)
	}

	return builder.String(), nil
}

func (a *app) queryRequiredValue(ctx context.Context, metricName string, labels map[string]string) (float64, error) {
	query := fmt.Sprintf("sum(%s%s)", metricName, buildSelector(labels))
	results, err := a.prom.Query(ctx, query)
	if err != nil {
		return 0, err
	}
	if len(results) == 0 {
		return 0, fmt.Errorf("no samples returned for %s", metricName)
	}

	return results[0].Value, nil
}

func (a *app) queryOptionalValue(ctx context.Context, metricName string, labels map[string]string) (float64, bool) {
	value, err := a.queryRequiredValue(ctx, metricName, labels)
	if err != nil {
		return 0, false
	}
	return value, true
}

func newPromClientFromEnv() (*promClient, error) {
	baseURL := getEnvOrDefault("PROM_URL", defaultPromURL)
	rawURL, err := url.Parse(baseURL)
	if err != nil {
		return nil, fmt.Errorf("invalid PROM_URL %q: %w", baseURL, err)
	}

	bearerToken := strings.TrimSpace(os.Getenv("PROM_BEARER_TOKEN"))
	if bearerToken == "" {
		tokenFile := getEnvOrDefault("PROM_TOKEN_FILE", defaultPromTokenFile)
		tokenData, err := os.ReadFile(tokenFile)
		if err != nil {
			return nil, fmt.Errorf("failed to read token file %q: %w", tokenFile, err)
		}
		bearerToken = strings.TrimSpace(string(tokenData))
	}

	insecureSkipVerify, err := strconv.ParseBool(getEnvOrDefault("PROM_INSECURE_SKIP_VERIFY", "false"))
	if err != nil {
		return nil, fmt.Errorf("invalid PROM_INSECURE_SKIP_VERIFY value: %w", err)
	}

	rootCAs, _ := x509.SystemCertPool()
	if rootCAs == nil {
		rootCAs = x509.NewCertPool()
	}

	if !insecureSkipVerify {
		caFile := getEnvOrDefault("PROM_CA_FILE", defaultPromCAFile)
		caData, err := os.ReadFile(caFile)
		if err != nil {
			return nil, fmt.Errorf("failed to read CA file %q: %w", caFile, err)
		}

		if ok := rootCAs.AppendCertsFromPEM(caData); !ok {
			return nil, fmt.Errorf("failed to parse CA certs from %q", caFile)
		}
	}

	httpClient := &http.Client{
		Timeout: 20 * time.Second,
		Transport: &http.Transport{
			TLSClientConfig: &tls.Config{
				MinVersion:         tls.VersionTLS12,
				InsecureSkipVerify: insecureSkipVerify, //nolint:gosec
				RootCAs:            rootCAs,
			},
		},
	}

	return &promClient{
		baseURL:     rawURL,
		bearerToken: bearerToken,
		httpClient:  httpClient,
	}, nil
}

func (p *promClient) Query(ctx context.Context, expr string) ([]promSample, error) {
	endpoint := *p.baseURL
	endpoint.Path = strings.TrimSuffix(endpoint.Path, "/") + "/api/v1/query"

	queryValues := endpoint.Query()
	queryValues.Set("query", expr)
	endpoint.RawQuery = queryValues.Encode()

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint.String(), nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+p.bearerToken)

	resp, err := p.httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 16*1024))
		return nil, fmt.Errorf("prometheus query failed with status %s: %s", resp.Status, strings.TrimSpace(string(body)))
	}

	var parsed promQueryResponse
	if err := json.NewDecoder(resp.Body).Decode(&parsed); err != nil {
		return nil, err
	}

	if parsed.Status != "success" {
		return nil, fmt.Errorf("prometheus query returned status %q: %s", parsed.Status, parsed.Error)
	}

	if parsed.Data.ResultType != "vector" {
		return nil, fmt.Errorf("unsupported prometheus result type %q", parsed.Data.ResultType)
	}

	samples := make([]promSample, 0, len(parsed.Data.Result))
	for _, result := range parsed.Data.Result {
		value, err := parsePrometheusValue(result.Value)
		if err != nil {
			continue
		}

		samples = append(samples, promSample{
			Labels: result.Metric,
			Value:  value,
		})
	}

	sort.Slice(samples, func(i, j int) bool {
		return samples[i].Value > samples[j].Value
	})

	return samples, nil
}

func parsePrometheusValue(raw []any) (float64, error) {
	if len(raw) < 2 {
		return 0, errors.New("missing prometheus sample value")
	}

	switch v := raw[1].(type) {
	case string:
		return strconv.ParseFloat(v, 64)
	case float64:
		return v, nil
	default:
		return 0, fmt.Errorf("unsupported prometheus value type %T", raw[1])
	}
}

func parseTopTargetsArgs(rawArgs map[string]any) (topTargetsArgs, error) {
	args := topTargetsArgs{
		Resource: "cpu",
		Limit:    5,
	}

	if value, ok, err := readStringArg(rawArgs, "resource"); err != nil {
		return args, err
	} else if ok {
		args.Resource = strings.ToLower(value)
	}

	if _, ok := resources[args.Resource]; !ok {
		return args, fmt.Errorf("resource must be one of cpu, memory, gpu")
	}

	if value, ok, err := readIntArg(rawArgs, "limit"); err != nil {
		return args, err
	} else if ok {
		if value < 1 || value > 25 {
			return args, fmt.Errorf("limit must be between 1 and 25")
		}
		args.Limit = value
	}

	if value, ok, err := readStringArg(rawArgs, "cluster"); err != nil {
		return args, err
	} else if ok {
		args.Cluster = value
	}

	if value, ok, err := readStringArg(rawArgs, "namespace"); err != nil {
		return args, err
	} else if ok {
		args.Namespace = value
	}

	return args, nil
}

func parseExplainTargetArgs(rawArgs map[string]any) (explainTargetArgs, error) {
	args := explainTargetArgs{
		Resource: "cpu",
	}

	if value, ok, err := readStringArg(rawArgs, "resource"); err != nil {
		return args, err
	} else if ok {
		args.Resource = strings.ToLower(value)
	}

	if _, ok := resources[args.Resource]; !ok {
		return args, fmt.Errorf("resource must be one of cpu, memory, gpu")
	}

	if value, ok, err := readStringArg(rawArgs, "cluster"); err != nil {
		return args, err
	} else if ok {
		args.Cluster = value
	}

	if value, ok, err := readStringArg(rawArgs, "namespace"); err != nil {
		return args, err
	} else if ok {
		args.Namespace = value
	}
	if args.Namespace == "" {
		return args, fmt.Errorf("namespace is required")
	}

	if value, ok, err := readStringArg(rawArgs, "workload"); err != nil {
		return args, err
	} else if ok {
		args.Workload = value
	}
	if args.Workload == "" {
		return args, fmt.Errorf("workload is required")
	}

	if value, ok, err := readStringArg(rawArgs, "workload_type"); err != nil {
		return args, err
	} else if ok {
		args.WorkloadType = value
	}

	return args, nil
}

func parseGPUInsightsArgs(rawArgs map[string]any) (gpuInsightsArgs, error) {
	args := gpuInsightsArgs{
		Limit: 5,
	}

	if value, ok, err := readIntArg(rawArgs, "limit"); err != nil {
		return args, err
	} else if ok {
		if value < 1 || value > 25 {
			return args, fmt.Errorf("limit must be between 1 and 25")
		}
		args.Limit = value
	}

	if value, ok, err := readStringArg(rawArgs, "cluster"); err != nil {
		return args, err
	} else if ok {
		args.Cluster = value
	}

	if value, ok, err := readStringArg(rawArgs, "namespace"); err != nil {
		return args, err
	} else if ok {
		args.Namespace = value
	}

	if value, ok, err := readStringArg(rawArgs, "workload"); err != nil {
		return args, err
	} else if ok {
		args.Workload = value
	}

	if args.Workload != "" && args.Namespace == "" {
		return args, fmt.Errorf("namespace is required when workload is set")
	}

	return args, nil
}

func readStringArg(rawArgs map[string]any, key string) (string, bool, error) {
	value, found := rawArgs[key]
	if !found {
		return "", false, nil
	}

	text, ok := value.(string)
	if !ok {
		return "", false, fmt.Errorf("%s must be a string", key)
	}

	return strings.TrimSpace(text), true, nil
}

func readIntArg(rawArgs map[string]any, key string) (int, bool, error) {
	value, found := rawArgs[key]
	if !found {
		return 0, false, nil
	}

	switch typedValue := value.(type) {
	case float64:
		if typedValue != float64(int(typedValue)) {
			return 0, false, fmt.Errorf("%s must be an integer", key)
		}
		return int(typedValue), true, nil
	case int:
		return typedValue, true, nil
	default:
		return 0, false, fmt.Errorf("%s must be an integer", key)
	}
}

func buildSelector(labels map[string]string) string {
	if len(labels) == 0 {
		return ""
	}

	keys := make([]string, 0, len(labels))
	for key, value := range labels {
		if strings.TrimSpace(value) == "" {
			continue
		}
		keys = append(keys, key)
	}
	if len(keys) == 0 {
		return ""
	}

	sort.Strings(keys)

	selectorEntries := make([]string, 0, len(keys))
	for _, key := range keys {
		selectorEntries = append(
			selectorEntries,
			fmt.Sprintf(`%s="%s"`, key, escapePrometheusLabelValue(labels[key])),
		)
	}

	return "{" + strings.Join(selectorEntries, ",") + "}"
}

func labelsForWorkloadSeries(allLabels map[string]string) map[string]string {
	labelKeys := []string{
		"cluster",
		"namespace",
		"workload",
		"workload_type",
		"aggregation",
		"profile",
	}

	selected := make(map[string]string)
	for _, key := range labelKeys {
		if value, found := allLabels[key]; found && value != "" {
			selected[key] = value
		}
	}

	return selected
}

func escapePrometheusLabelValue(value string) string {
	replacer := strings.NewReplacer(
		`\`, `\\`,
		`"`, `\"`,
		"\n", `\n`,
	)
	return replacer.Replace(value)
}

func computeConfidence(request, usage float64) (string, string) {
	switch {
	case request <= 0:
		return "low", "request is zero, recommendation confidence is reduced"
	case usage <= 0:
		return "low", "observed usage is zero, likely idle or insufficient data"
	}

	ratio := usage / request
	switch {
	case ratio < 0.5:
		return "high", "observed usage is below 50% of requested resources"
	case ratio < 0.8:
		return "medium", "observed usage is below 80% of requested resources"
	default:
		return "low", "observed usage is close to requested resources"
	}
}

func formatResourceValue(resource string, value float64) string {
	switch resource {
	case "memory":
		return formatBytes(value)
	case "gpu":
		return fmt.Sprintf("%.2f GPU", value)
	default:
		return fmt.Sprintf("%.3f cores", value)
	}
}

func formatBytes(value float64) string {
	const (
		kib = 1024
		mib = 1024 * kib
		gib = 1024 * mib
		tib = 1024 * gib
	)

	switch {
	case value >= tib:
		return fmt.Sprintf("%.2f TiB", value/tib)
	case value >= gib:
		return fmt.Sprintf("%.2f GiB", value/gib)
	case value >= mib:
		return fmt.Sprintf("%.2f MiB", value/mib)
	case value >= kib:
		return fmt.Sprintf("%.2f KiB", value/kib)
	default:
		return fmt.Sprintf("%.2f B", value)
	}
}

func emptyDash(value string) string {
	if strings.TrimSpace(value) == "" {
		return "-"
	}

	return value
}

func getEnvOrDefault(key, defaultValue string) string {
	value := strings.TrimSpace(os.Getenv(key))
	if value == "" {
		return defaultValue
	}
	return value
}

func newLogger(level string) *slog.Logger {
	var slogLevel slog.Level
	switch strings.ToLower(strings.TrimSpace(level)) {
	case "debug":
		slogLevel = slog.LevelDebug
	case "warn":
		slogLevel = slog.LevelWarn
	case "error":
		slogLevel = slog.LevelError
	default:
		slogLevel = slog.LevelInfo
	}

	return slog.New(slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{Level: slogLevel}))
}

func applyCORSHeaders(w http.ResponseWriter) {
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Access-Control-Allow-Methods", "POST,OPTIONS")
	w.Header().Set("Access-Control-Allow-Headers", "Content-Type,Authorization")
}

func matchesBearerToken(header, expectedToken string) bool {
	const bearerPrefix = "Bearer "

	if !strings.HasPrefix(header, bearerPrefix) {
		return false
	}

	token := strings.TrimSpace(strings.TrimPrefix(header, bearerPrefix))
	return token == expectedToken
}

func (a *app) writeJSONRPCError(w http.ResponseWriter, req jsonRPCRequest, code int, message string) {
	responseID := json.RawMessage("null")
	if req.ID != nil {
		responseID = *req.ID
	}

	resp := jsonRPCResponse{
		JSONRPC: "2.0",
		ID:      responseID,
		Error: &jsonRPCError{
			Code:    code,
			Message: message,
		},
	}

	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(resp); err != nil {
		a.logger.Error("failed to encode JSON-RPC error", "error", err)
	}
}

func mcpTools() []map[string]any {
	return []map[string]any{
		{
			"name":        "get_top_rightsizing_targets",
			"description": "List top workload targets by over-provisioned resources (request minus recommendation).",
			"inputSchema": map[string]any{
				"type": "object",
				"properties": map[string]any{
					"resource": map[string]any{
						"type":        "string",
						"description": "Resource type to evaluate: cpu, memory, or gpu.",
						"enum":        []string{"cpu", "memory", "gpu"},
					},
					"limit": map[string]any{
						"type":        "integer",
						"description": "Number of results to return (1-25).",
						"minimum":     1,
						"maximum":     25,
					},
					"cluster": map[string]any{
						"type":        "string",
						"description": "Optional cluster label filter.",
					},
					"namespace": map[string]any{
						"type":        "string",
						"description": "Optional namespace label filter.",
					},
				},
				"additionalProperties": false,
			},
		},
		{
			"name":        "explain_rightsizing_target",
			"description": "Explain current request, usage, recommendation, and potential savings for one workload target.",
			"inputSchema": map[string]any{
				"type": "object",
				"properties": map[string]any{
					"resource": map[string]any{
						"type":        "string",
						"description": "Resource type: cpu, memory, or gpu.",
						"enum":        []string{"cpu", "memory", "gpu"},
					},
					"cluster": map[string]any{
						"type":        "string",
						"description": "Optional cluster label filter.",
					},
					"namespace": map[string]any{
						"type":        "string",
						"description": "Namespace of the workload.",
					},
					"workload": map[string]any{
						"type":        "string",
						"description": "Workload name.",
					},
					"workload_type": map[string]any{
						"type":        "string",
						"description": "Optional workload type (Deployment, StatefulSet, etc.).",
					},
				},
				"required":             []string{"namespace", "workload"},
				"additionalProperties": false,
			},
		},
		{
			"name":        "get_gpu_rightsizing_insights",
			"description": "Return top GPU right-sizing insights with request, usage, recommendation, and device-level metrics.",
			"inputSchema": map[string]any{
				"type": "object",
				"properties": map[string]any{
					"limit": map[string]any{
						"type":        "integer",
						"description": "Number of top workloads to return (1-25).",
						"minimum":     1,
						"maximum":     25,
					},
					"cluster": map[string]any{
						"type":        "string",
						"description": "Optional cluster label filter.",
					},
					"namespace": map[string]any{
						"type":        "string",
						"description": "Optional namespace label filter. Required if workload is set.",
					},
					"workload": map[string]any{
						"type":        "string",
						"description": "Optional workload name. If provided, returns details for that single workload.",
					},
				},
				"additionalProperties": false,
			},
		},
	}
}
