// Copyright (c) Red Hat, Inc.
// Copyright Contributors to the Open Cluster Management project
// Licensed under the Apache License 2.0

package rsworkload

import (
	"testing"

	rsutility "github.com/stolostron/multicluster-observability-operator/operators/multiclusterobservability/controllers/analytics/rightsizing/rs-utility"
	"github.com/stretchr/testify/assert"
)

func TestGeneratePrometheusRule_IncludesMappingRule(t *testing.T) {
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

	rule, err := GeneratePrometheusRuleWithFeatures(config, true, true)
	assert.NoError(t, err)
	assert.Equal(t, PrometheusRuleName, rule.Name)
	assert.Len(t, rule.Spec.Groups, 2)
	assert.Equal(t, "acm-right-sizing-workload-5m.rules", rule.Spec.Groups[0].Name)
	assert.Equal(t, "acm_rs:pod_workload:relabel:5m", rule.Spec.Groups[0].Rules[0].Record)
	assert.Contains(t, rule.Spec.Groups[0].Rules[0].Expr.String(), `namespace=~"ns-a"`)
}

