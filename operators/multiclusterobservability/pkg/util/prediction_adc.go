// Copyright (c) Red Hat, Inc.
// Copyright Contributors to the Open Cluster Management project
// Licensed under the Apache License 2.0

package util

import (
	"encoding/json"
	"strings"

	obv1beta2 "github.com/stolostron/multicluster-observability-operator/operators/multiclusterobservability/api/v1beta2"
	corev1 "k8s.io/api/core/v1"
)

// PredictionADCEnabledValue returns "enabled" or "disabled" for the
// platformRightSizingPrediction AddOnDeploymentConfig key (MCOA matches "enabled" exactly).
func PredictionADCEnabledValue(predictionEnabled bool) string {
	if predictionEnabled {
		return "enabled"
	}
	return "disabled"
}

// PredictionADCProviderValue returns the provider type for platformRightSizingPredictionProvider.
// When prediction is disabled, returns an empty string.
func PredictionADCProviderValue(pred obv1beta2.PlatformPredictionSpec) string {
	if !pred.Enabled {
		return ""
	}
	t := strings.TrimSpace(pred.Provider.Type)
	if t == "" {
		return "builtin"
	}
	return t
}

// predictionADCConfig bundles fields mirrored into the ADC prediction config JSON key.
type predictionADCConfig struct {
	TrainingIntervalHours   int                          `json:"trainingIntervalHours,omitempty"`
	HistoryDays             int                          `json:"historyDays,omitempty"`
	SafetyMarginPercent     int                          `json:"safetyMarginPercent,omitempty"`
	CustomEndpointURL       string                       `json:"customEndpointURL,omitempty"`
	ONNXModelConfigMapRef   *corev1.LocalObjectReference `json:"onnxModelConfigMapRef,omitempty"`
	DataExfiltrationConsent bool                         `json:"dataExfiltrationConsent,omitempty"`
	APIKey                  string                       `json:"apiKey,omitempty"`
	ConsentGiven            bool                         `json:"consentGiven,omitempty"`
}

// BuildPredictionADCConfigJSON returns JSON for platformRightSizingPredictionConfig.
// externalAPIKey is set when the hub resolves an ExternalAPIKeySecretRef (analytics controller only).
func BuildPredictionADCConfigJSON(pred obv1beta2.PlatformPredictionSpec, externalAPIKey string) (string, error) {
	if !pred.Enabled {
		return "{}", nil
	}
	c := predictionADCConfig{
		TrainingIntervalHours:   pred.Config.TrainingIntervalHours,
		HistoryDays:             pred.Config.HistoryDays,
		SafetyMarginPercent:     pred.Config.SafetyMarginPercent,
		CustomEndpointURL:       pred.Provider.CustomEndpointURL,
		ONNXModelConfigMapRef:   pred.Provider.ONNXModelConfigMapRef,
		DataExfiltrationConsent: pred.Provider.DataExfiltrationConsent,
	}
	if externalAPIKey != "" {
		c.APIKey = externalAPIKey
		c.ConsentGiven = pred.Provider.DataExfiltrationConsent
	}
	b, err := json.Marshal(c)
	if err != nil {
		return "", err
	}
	return string(b), nil
}
