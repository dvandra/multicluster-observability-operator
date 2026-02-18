// Copyright (c) Red Hat, Inc.
// Copyright Contributors to the Open Cluster Management project
// Licensed under the Apache License 2.0

package rsgpu

import (
	"testing"

	rsutility "github.com/stolostron/multicluster-observability-operator/operators/multiclusterobservability/controllers/analytics/rightsizing/rs-utility"
	"github.com/stretchr/testify/assert"
)

func TestGeneratePrometheusRule_IncludesNamespaceGPU(t *testing.T) {
	config := rsutility.RSNamespaceConfigMapData{
		PrometheusRuleConfig: rsutility.RSPrometheusRuleConfig{
			NamespaceFilterCriteria: struct {
				InclusionCriteria []string "yaml:\"inclusionCriteria\""
				ExclusionCriteria []string "yaml:\"exclusionCriteria\""
			}{
				InclusionCriteria: []string{"ns-a"},
			},
			RecommendationPercentage: 110,
		},
	}

	rule, err := GeneratePrometheusRuleWithMapping(config, true)
	assert.NoError(t, err)
	assert.Equal(t, PrometheusRuleName, rule.Name)
	assert.Equal(t, "k8s", rule.Labels["prometheus"])
	assert.Equal(t, "alert-rules", rule.Labels["role"])
	assert.Len(t, rule.Spec.Groups, 6)
	// First rule group should include namespace GPU request expression.
	assert.Contains(t, rule.Spec.Groups[0].Rules[0].Expr.String(), `resource=~"nvidia.com/gpu|amd.com/gpu"`)
}

func TestGeneratePrometheusRule_IncludesWorkloadMappingForBatchControllers(t *testing.T) {
	config := rsutility.RSNamespaceConfigMapData{
		PrometheusRuleConfig: rsutility.RSPrometheusRuleConfig{
			NamespaceFilterCriteria: struct {
				InclusionCriteria []string "yaml:\"inclusionCriteria\""
				ExclusionCriteria []string "yaml:\"exclusionCriteria\""
			}{
				InclusionCriteria: []string{"ns-a"},
			},
			RecommendationPercentage: 110,
		},
	}

	rule, err := GeneratePrometheusRuleWithMapping(config, true)
	assert.NoError(t, err)

	// Workload+pod mapping is generated in the first workload/pod 5m rule group.
	var mappingExpr string
	for _, rg := range rule.Spec.Groups {
		for _, r := range rg.Rules {
			if r.Record == "acm_rs:pod_workload:relabel:5m" {
				mappingExpr = r.Expr.String()
			}
		}
	}
	assert.NotEmpty(t, mappingExpr)
	assert.Contains(t, mappingExpr, `owner_kind="Job"`)
	assert.Contains(t, mappingExpr, `kube_job_owner`)
	assert.Contains(t, mappingExpr, `owner_kind="CronJob"`)
	assert.Contains(t, mappingExpr, `"workload_type", "ReplicaSet"`)
}
