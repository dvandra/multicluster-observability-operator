package v1beta2

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestPlatformCapabilitiesSpec_MarshalJSON_RightsizingOnly(t *testing.T) {
	spec := PlatformCapabilitiesSpec{
		Analytics: PlatformAnalyticsSpec{
			NamespaceRightSizingRecommendation: PlatformRightSizingRecommendationSpec{
				Enabled: true,
			},
			VirtualizationRightSizingRecommendation: PlatformRightSizingRecommendationSpec{
				Enabled: true,
			},
		},
	}

	data, err := json.Marshal(spec)
	if err != nil {
		t.Fatalf("marshal failed: %v", err)
	}
	jsonStr := string(data)

	if !strings.Contains(jsonStr, "namespaceRightSizingRecommendation") {
		t.Fatalf("expected namespace right-sizing in JSON, got: %s", jsonStr)
	}
	if !strings.Contains(jsonStr, "virtualizationRightSizingRecommendation") {
		t.Fatalf("expected virtualization right-sizing in JSON, got: %s", jsonStr)
	}
	if strings.Contains(jsonStr, "incidentDetection") {
		t.Fatalf("did not expect incidentDetection when disabled, got: %s", jsonStr)
	}
	if strings.Contains(jsonStr, `"logs"`) {
		t.Fatalf("did not expect logs section when disabled, got: %s", jsonStr)
	}
	if strings.Contains(jsonStr, `"metrics"`) {
		t.Fatalf("did not expect metrics section when disabled, got: %s", jsonStr)
	}
}

