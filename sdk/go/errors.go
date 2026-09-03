// Package synapse is a Go client SDK for the Synapse SaaS Framework API.
//
// Two credential modes: API key (sk_…, org pinned server-side) or an access
// token from the console login flow.
package synapse

import (
	"encoding/json"
	"fmt"
)

// Problem mirrors the API's problem+json error documents.
type Problem map[string]any

func (p Problem) Title() string {
	if s, ok := p["title"].(string); ok {
		return s
	}
	return ""
}

// SynapseError is any non-2xx API response.
type SynapseError struct {
	Status int
	Body   Problem
}

func (e *SynapseError) Error() string {
	if d, ok := e.Body["detail"].(string); ok && d != "" {
		return d
	}
	if t := e.Body.Title(); t != "" {
		return t
	}
	return fmt.Sprintf("API error %d", e.Status)
}

// AuthError is 401 — bad credentials (or revoked/expired key).
type AuthError struct{ SynapseError }

// NotFoundError is 404 — missing resource, or cross-tenant (identical by design).
type NotFoundError struct{ SynapseError }

// LimitError is 402 — plan limit exceeded.
type LimitError struct{ SynapseError }

// Metric returns which quota tripped, when present.
func (e *LimitError) Metric() string {
	if s, ok := e.Body["metric"].(string); ok {
		return s
	}
	return ""
}

// FeatureGatedError is 403 feature_not_entitled.
type FeatureGatedError struct{ SynapseError }

// Feature returns the gated feature key.
func (e *FeatureGatedError) Feature() string {
	if s, ok := e.Body["feature"].(string); ok {
		return s
	}
	return ""
}

// AvailableIn lists plans that carry the feature.
func (e *FeatureGatedError) AvailableIn() []string {
	raw, ok := e.Body["available_in"].([]any)
	if !ok {
		return nil
	}
	out := make([]string, 0, len(raw))
	for _, v := range raw {
		if s, ok := v.(string); ok {
			out = append(out, s)
		}
	}
	return out
}

func errorFor(status int, body json.RawMessage) error {
	problem := Problem{}
	_ = json.Unmarshal(body, &problem)
	switch {
	case status == 401:
		return &AuthError{SynapseError{status, problem}}
	case status == 404:
		return &NotFoundError{SynapseError{status, problem}}
	case status == 402:
		return &LimitError{SynapseError{status, problem}}
	case status == 403 && problem["feature"] != nil:
		return &FeatureGatedError{SynapseError{status, problem}}
	}
	return &SynapseError{status, problem}
}
