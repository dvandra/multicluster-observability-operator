// Copyright (c) Red Hat, Inc.
// Copyright Contributors to the Open Cluster Management project
// Licensed under the Apache License 2.0

package rightsizing

import (
	"context"
	"testing"

	mcov1beta2 "github.com/stolostron/multicluster-observability-operator/operators/multiclusterobservability/api/v1beta2"
	"github.com/stretchr/testify/require"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	clusterv1beta1 "open-cluster-management.io/api/cluster/v1beta1"
	policyv1 "open-cluster-management.io/governance-policy-propagator/api/v1"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
)

func setupTestScheme(t *testing.T) *runtime.Scheme {
	scheme := runtime.NewScheme()
	require.NoError(t, corev1.AddToScheme(scheme))
	require.NoError(t, mcov1beta2.AddToScheme(scheme))
	require.NoError(t, policyv1.AddToScheme(scheme))
	require.NoError(t, clusterv1beta1.AddToScheme(scheme))
	return scheme
}

func newTestMCO(binding string, enabled bool) *mcov1beta2.MultiClusterObservability {
	return &mcov1beta2.MultiClusterObservability{
		ObjectMeta: metav1.ObjectMeta{Name: "observability"},
		Spec: mcov1beta2.MultiClusterObservabilitySpec{
			Capabilities: &mcov1beta2.CapabilitiesSpec{
				Platform: &mcov1beta2.PlatformCapabilitiesSpec{
					Analytics: mcov1beta2.PlatformAnalyticsSpec{
						NamespaceRightSizingRecommendation: mcov1beta2.PlatformRightSizingRecommendationSpec{
							Enabled:          enabled,
							NamespaceBinding: binding,
						},
						VirtualizationRightSizingRecommendation: mcov1beta2.PlatformRightSizingRecommendationSpec{
							Enabled:          enabled,
							NamespaceBinding: binding,
						},
					},
				},
			},
		},
	}
}

func TestCreateRightSizingComponent_FeatureEnabled(t *testing.T) {
	scheme := setupTestScheme(t)

	mco := newTestMCO("custom-ns", true)

	client := fake.NewClientBuilder().
		WithScheme(scheme).
		WithObjects(mco).
		Build()

	err := CreateRightSizingComponent(context.TODO(), client, mco)
	require.NoError(t, err)
}

func TestCreateRightSizingComponent_FeatureDisabled(t *testing.T) {
	scheme := setupTestScheme(t)

	mco := newTestMCO("", false)

	client := fake.NewClientBuilder().
		WithScheme(scheme).
		WithObjects(mco).
		Build()

	err := CreateRightSizingComponent(context.TODO(), client, mco)
	require.NoError(t, err)
}
