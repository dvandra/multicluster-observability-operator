// Copyright (c) Red Hat, Inc.
// Copyright Contributors to the Open Cluster Management project
// Licensed under the Apache License 2.0

package main

import "testing"

func TestBuildSelectorSortedAndEscaped(t *testing.T) {
	t.Parallel()

	selector := buildSelector(map[string]string{
		"workload":  `app-"demo"`,
		"namespace": "team-a",
		"cluster":   `local\cluster`,
	})

	expected := `{cluster="local\\cluster",namespace="team-a",workload="app-\"demo\""}`
	if selector != expected {
		t.Fatalf("unexpected selector: got %q, want %q", selector, expected)
	}
}

func TestParseTopTargetsArgsDefaults(t *testing.T) {
	t.Parallel()

	args, err := parseTopTargetsArgs(map[string]any{})
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}

	if args.Resource != "cpu" {
		t.Fatalf("expected default resource cpu, got %q", args.Resource)
	}
	if args.Limit != 5 {
		t.Fatalf("expected default limit 5, got %d", args.Limit)
	}
}

func TestParseTopTargetsArgsValidation(t *testing.T) {
	t.Parallel()

	_, err := parseTopTargetsArgs(map[string]any{
		"resource": "disk",
	})
	if err == nil {
		t.Fatalf("expected validation error for unsupported resource")
	}

	_, err = parseTopTargetsArgs(map[string]any{
		"resource": "gpu",
		"limit":    100.0,
	})
	if err == nil {
		t.Fatalf("expected validation error for out-of-range limit")
	}
}

func TestParseExplainTargetArgsValidation(t *testing.T) {
	t.Parallel()

	_, err := parseExplainTargetArgs(map[string]any{
		"resource": "cpu",
		"workload": "my-workload",
	})
	if err == nil {
		t.Fatalf("expected validation error when namespace is missing")
	}

	_, err = parseExplainTargetArgs(map[string]any{
		"resource":  "cpu",
		"namespace": "team-a",
	})
	if err == nil {
		t.Fatalf("expected validation error when workload is missing")
	}
}

func TestParseGPUInsightsArgsValidation(t *testing.T) {
	t.Parallel()

	_, err := parseGPUInsightsArgs(map[string]any{
		"workload": "gpu-job",
	})
	if err == nil {
		t.Fatalf("expected validation error when workload is set without namespace")
	}
}

func TestComputeConfidence(t *testing.T) {
	t.Parallel()

	level, _ := computeConfidence(10, 2)
	if level != "high" {
		t.Fatalf("expected high confidence, got %q", level)
	}

	level, _ = computeConfidence(10, 6)
	if level != "medium" {
		t.Fatalf("expected medium confidence, got %q", level)
	}

	level, _ = computeConfidence(10, 9)
	if level != "low" {
		t.Fatalf("expected low confidence, got %q", level)
	}
}
