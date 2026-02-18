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
	assert.Len(t, rule.Spec.Groups, 6)
	// First rule group should include namespace GPU request expression.
	assert.Contains(t, rule.Spec.Groups[0].Rules[0].Expr.String(), `resource=~"nvidia.com/gpu|amd.com/gpu"`)
}
