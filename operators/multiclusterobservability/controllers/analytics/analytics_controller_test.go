// Copyright (c) Red Hat, Inc.
// Copyright Contributors to the Open Cluster Management project
// Licensed under the Apache License 2.0

package analytics

import (
	"context"
	"testing"

	"github.com/stretchr/testify/require"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
	logf "sigs.k8s.io/controller-runtime/pkg/log"

	mcov1beta2 "github.com/stolostron/multicluster-observability-operator/operators/multiclusterobservability/api/v1beta2"
	rsnamespace "github.com/stolostron/multicluster-observability-operator/operators/multiclusterobservability/controllers/analytics/rightsizing/rs-namespace"
	rsutility "github.com/stolostron/multicluster-observability-operator/operators/multiclusterobservability/controllers/analytics/rightsizing/rs-utility"
	clusterv1beta1 "open-cluster-management.io/api/cluster/v1beta1"
	policyv1 "open-cluster-management.io/governance-policy-propagator/api/v1"
)

func setupTestScheme(t *testing.T) *runtime.Scheme {
	scheme := runtime.NewScheme()
	require.NoError(t, corev1.AddToScheme(scheme))
	require.NoError(t, mcov1beta2.AddToScheme(scheme))
	require.NoError(t, policyv1.AddToScheme(scheme))
	require.NoError(t, clusterv1beta1.AddToScheme(scheme))
	return scheme
}

func newTestMCO(binding string, enabled bool, paused bool) *mcov1beta2.MultiClusterObservability {
	mco := &mcov1beta2.MultiClusterObservability{
		ObjectMeta: metav1.ObjectMeta{Name: "observability"},
		Spec: mcov1beta2.MultiClusterObservabilitySpec{
			Capabilities: &mcov1beta2.CapabilitiesSpec{
				Platform: &mcov1beta2.PlatformCapabilitiesSpec{
					Analytics: mcov1beta2.PlatformAnalyticsSpec{
						NamespaceRightSizingRecommendation: mcov1beta2.PlatformRightSizingRecommendationSpec{
							Enabled:          enabled,
							NamespaceBinding: binding,
						},
					},
				},
			},
		},
	}
	if paused {
		if mco.Annotations == nil {
			mco.Annotations = map[string]string{}
		}
		mco.Annotations["mco-pause"] = "true"
	}
	return mco
}

func TestAnalyticsReconciler_FeatureEnabled(t *testing.T) {
	scheme := setupTestScheme(t)

	mco := newTestMCO("custom-ns", true, false)

	// minimal required configmap for namespace RS path used by analytics controller
	configMap := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      rsnamespace.ConfigMapName,
			Namespace: rsutility.DefaultNamespace,
		},
		Data: map[string]string{
			"config.yaml": `
                prometheusRuleConfig:
                namespaceFilterCriteria:
                    inclusionCriteria: ["ns1"]
                    exclusionCriteria: []
                labelFilterCriteria: []
                recommendationPercentage: 110
                placementConfiguration:
                predicates: []
            `,
		},
	}

	c := fake.NewClientBuilder().
		WithScheme(scheme).
		WithObjects(mco, configMap).
		Build()

	r := &AnalyticsReconciler{Client: c, Scheme: scheme}
	_, err := r.Reconcile(context.TODO(), ctrl.Request{})
	require.NoError(t, err)
}

func TestAnalyticsReconciler_FeatureDisabled(t *testing.T) {
	scheme := setupTestScheme(t)

	mco := newTestMCO("", false, false)

	c := fake.NewClientBuilder().
		WithScheme(scheme).
		WithObjects(mco).
		Build()

	r := &AnalyticsReconciler{Client: c, Scheme: scheme}
	_, err := r.Reconcile(context.TODO(), ctrl.Request{})
	require.NoError(t, err)
}

func TestAnalyticsReconciler_PausedAnnotation(t *testing.T) {
	scheme := setupTestScheme(t)

	mco := newTestMCO("", true, true)

	c := fake.NewClientBuilder().
		WithScheme(scheme).
		WithObjects(mco).
		Build()

	r := &AnalyticsReconciler{Client: c, Scheme: scheme}
	_, err := r.Reconcile(context.TODO(), ctrl.Request{})
	require.NoError(t, err)
}

// Verifies default right-sizing flags are persisted when absent.
func TestAnalyticsReconciler_DefaultsPersistedWhenAbsent(t *testing.T) {
	scheme := setupTestScheme(t)

	mco := &mcov1beta2.MultiClusterObservability{
		ObjectMeta: metav1.ObjectMeta{Name: "observability"},
	}

	c := fake.NewClientBuilder().
		WithScheme(scheme).
		WithObjects(mco).
		Build()

	r := &AnalyticsReconciler{Client: c, Scheme: scheme}
	updated, err := r.ensureRightSizingDefaults(context.TODO(), mco, logf.Log.WithName("test"))
	require.NoError(t, err)

	// Verify returned instance has defaults set
	require.NotNil(t, updated.Spec.Capabilities)
	require.NotNil(t, updated.Spec.Capabilities.Platform)
	require.True(t, updated.Spec.Capabilities.Platform.Analytics.NamespaceRightSizingRecommendation.Enabled)
	require.True(t, updated.Spec.Capabilities.Platform.Analytics.VirtualizationRightSizingRecommendation.Enabled)

	// Verify persisted state in the cluster
	persisted := &mcov1beta2.MultiClusterObservability{}
	err = c.Get(context.TODO(), types.NamespacedName{Name: "observability"}, persisted)
	require.NoError(t, err)
	require.True(t, persisted.Spec.Capabilities.Platform.Analytics.NamespaceRightSizingRecommendation.Enabled)
	require.True(t, persisted.Spec.Capabilities.Platform.Analytics.VirtualizationRightSizingRecommendation.Enabled)
}

// Verifies unrelated analytics/platform sections are stripped when defaults are applied (empty sections removed).
func TestAnalyticsReconciler_StripsUnrelatedSections(t *testing.T) {
	scheme := setupTestScheme(t)

	raw := &unstructured.Unstructured{
		Object: map[string]any{
			"apiVersion": "observability.open-cluster-management.io/v1beta2",
			"kind":       "MultiClusterObservability",
			"metadata": map[string]any{
				"name": "observability",
			},
			"spec": map[string]any{
				"capabilities": map[string]any{
					"platform": map[string]any{
						"analytics": map[string]any{
							"incidentDetection": map[string]any{},
						},
						"logs":    map[string]any{},
						"metrics": map[string]any{},
					},
				},
			},
		},
	}
	raw.SetGroupVersionKind(raw.GroupVersionKind())

	c := fake.NewClientBuilder().
		WithScheme(scheme).
		WithObjects(raw).
		Build()

	r := &AnalyticsReconciler{Client: c, Scheme: scheme}
	_, err := r.ensureRightSizingDefaults(context.TODO(), &mcov1beta2.MultiClusterObservability{ObjectMeta: metav1.ObjectMeta{Name: "observability"}}, logf.Log.WithName("test"))
	require.NoError(t, err)

	got := &unstructured.Unstructured{}
	got.SetGroupVersionKind(raw.GroupVersionKind())
	require.NoError(t, c.Get(context.TODO(), types.NamespacedName{Name: "observability"}, got))

	_, foundIncident, _ := unstructured.NestedFieldNoCopy(got.Object, "spec", "capabilities", "platform", "analytics", "incidentDetection")
	_, foundLogs, _ := unstructured.NestedFieldNoCopy(got.Object, "spec", "capabilities", "platform", "logs")
	_, foundMetrics, _ := unstructured.NestedFieldNoCopy(got.Object, "spec", "capabilities", "platform", "metrics")

	require.False(t, foundIncident)
	require.False(t, foundLogs)
	require.False(t, foundMetrics)
}

// Verifies we do NOT strip non-empty unrelated sections.
func TestAnalyticsReconciler_PreservesNonEmptyUnrelatedSections(t *testing.T) {
	scheme := setupTestScheme(t)

	raw := &unstructured.Unstructured{
		Object: map[string]any{
			"apiVersion": "observability.open-cluster-management.io/v1beta2",
			"kind":       "MultiClusterObservability",
			"metadata": map[string]any{
				"name": "observability",
			},
			"spec": map[string]any{
				"capabilities": map[string]any{
					"platform": map[string]any{
						"analytics": map[string]any{
							"incidentDetection": map[string]any{"enabled": false},
						},
						"logs": map[string]any{
							"collection": map[string]any{"enabled": true},
						},
						"metrics": map[string]any{
							"default": map[string]any{"enabled": true},
						},
					},
				},
			},
		},
	}
	raw.SetGroupVersionKind(raw.GroupVersionKind())

	c := fake.NewClientBuilder().
		WithScheme(scheme).
		WithObjects(raw).
		Build()

	r := &AnalyticsReconciler{Client: c, Scheme: scheme}
	_, err := r.ensureRightSizingDefaults(context.TODO(), &mcov1beta2.MultiClusterObservability{ObjectMeta: metav1.ObjectMeta{Name: "observability"}}, logf.Log.WithName("test"))
	require.NoError(t, err)

	got := &unstructured.Unstructured{}
	got.SetGroupVersionKind(raw.GroupVersionKind())
	require.NoError(t, c.Get(context.TODO(), types.NamespacedName{Name: "observability"}, got))

	incident, foundIncident, _ := unstructured.NestedMap(got.Object, "spec", "capabilities", "platform", "analytics", "incidentDetection")
	logs, foundLogs, _ := unstructured.NestedMap(got.Object, "spec", "capabilities", "platform", "logs")
	metrics, foundMetrics, _ := unstructured.NestedMap(got.Object, "spec", "capabilities", "platform", "metrics")

	require.True(t, foundIncident)
	require.True(t, foundLogs)
	require.True(t, foundMetrics)
	require.Equal(t, map[string]any{"enabled": false}, incident)
	require.Contains(t, logs, "collection")
	require.Contains(t, metrics, "default")
}

// Verifies reconcile is a no-op (no error) when no MCO CRs exist
func TestAnalyticsReconciler_NoMCO(t *testing.T) {
	scheme := setupTestScheme(t)

	c := fake.NewClientBuilder().
		WithScheme(scheme).
		Build()

	r := &AnalyticsReconciler{Client: c, Scheme: scheme}
	_, err := r.Reconcile(context.TODO(), ctrl.Request{})
	require.NoError(t, err)
}
