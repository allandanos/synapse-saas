package synapse

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"testing"
)

type roundTrip func(*http.Request) (*http.Response, error)

func (f roundTrip) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func testClient(t *testing.T, handle roundTrip) *Client {
	t.Helper()
	c, err := New("http://test", Options{
		APIKey:     "sk_test",
		OrgID:      "11111111-1111-1111-1111-111111111111",
		HTTPClient: &http.Client{Transport: handle},
	})
	if err != nil {
		t.Fatal(err)
	}
	return c
}

func jsonResponse(status int, body string) *http.Response {
	return &http.Response{
		StatusCode: status,
		Header:     http.Header{"Content-Type": []string{"application/json"}},
		Body:       io.NopCloser(strings.NewReader(body)),
	}
}

func TestAuthAndOrgHeaders(t *testing.T) {
	var gotAuth, gotOrg string
	c := testClient(t, func(r *http.Request) (*http.Response, error) {
		gotAuth = r.Header.Get("Authorization")
		gotOrg = r.Header.Get("X-Org-Id")
		return jsonResponse(200, `{"id":"u1"}`), nil
	})
	if _, err := c.Auth().Me(context.Background()); err != nil {
		t.Fatal(err)
	}
	if gotAuth != "Bearer sk_test" {
		t.Errorf("auth header = %q", gotAuth)
	}
	if gotOrg != "11111111-1111-1111-1111-111111111111" {
		t.Errorf("org header = %q", gotOrg)
	}
}

func TestConsumePayload(t *testing.T) {
	var body string
	c := testClient(t, func(r *http.Request) (*http.Response, error) {
		raw, _ := io.ReadAll(r.Body)
		body = string(raw)
		return jsonResponse(200, `{"total":5}`), nil
	})
	out, err := c.Usage().Consume(context.Background(), "api_requests", 5)
	if err != nil {
		t.Fatal(err)
	}
	if out["total"].(float64) != 5 {
		t.Errorf("total = %v", out["total"])
	}
	var parsed struct {
		Events []map[string]any `json:"events"`
	}
	if err := json.Unmarshal([]byte(body), &parsed); err != nil {
		t.Fatal(err)
	}
	if parsed.Events[0]["metric"] != "api_requests" || parsed.Events[0]["quantity"].(float64) != 5 {
		t.Errorf("payload = %s", body)
	}
}

func Test204ReturnsNoError(t *testing.T) {
	c := testClient(t, func(*http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: 204, Body: io.NopCloser(strings.NewReader(""))}, nil
	})
	if err := c.APIKeys().Revoke(context.Background(), "k1"); err != nil {
		t.Errorf("revoke: %v", err)
	}
}

func TestLimitErrorTyped(t *testing.T) {
	c := testClient(t, func(*http.Request) (*http.Response, error) {
		return jsonResponse(402, `{"title":"usage limit exceeded","metric":"api_requests","limit":100}`), nil
	})
	_, err := c.Usage().Consume(context.Background(), "api_requests", 500)
	var limitErr *LimitError
	if !errors.As(err, &limitErr) {
		t.Fatalf("want LimitError, got %T: %v", err, err)
	}
	if limitErr.Metric() != "api_requests" {
		t.Errorf("metric = %q", limitErr.Metric())
	}
}

func TestFeatureGateErrorTyped(t *testing.T) {
	c := testClient(t, func(*http.Request) (*http.Response, error) {
		return jsonResponse(403, `{"title":"feature not entitled","feature":"advanced_reports","available_in":["pro"]}`), nil
	})
	_, err := c.Subscription().Change(context.Background(), "pro")
	var gateErr *FeatureGatedError
	if !errors.As(err, &gateErr) {
		t.Fatalf("want FeatureGatedError, got %T: %v", err, err)
	}
	if gateErr.Feature() != "advanced_reports" {
		t.Errorf("feature = %q", gateErr.Feature())
	}
	if len(gateErr.AvailableIn()) != 1 || gateErr.AvailableIn()[0] != "pro" {
		t.Errorf("available_in = %v", gateErr.AvailableIn())
	}
}

func TestRequiresCredentials(t *testing.T) {
	if _, err := New("http://test", Options{}); err == nil {
		t.Error("expected error for missing credentials")
	}
}
