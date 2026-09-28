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

func TestPagesReadTotalHeader(t *testing.T) {
	var gotURL string
	c := testClient(t, func(r *http.Request) (*http.Response, error) {
		gotURL = r.URL.String()
		resp := jsonResponse(200, `[{"id":"a"},{"id":"b"}]`)
		resp.Header.Set("X-Total-Count", "7")
		return resp, nil
	})
	page, err := c.Invoices().List(context.Background(), Paging{Limit: 2, Offset: 4})
	if err != nil {
		t.Fatal(err)
	}
	if page.Total != 7 || len(page.Items) != 2 || page.Limit != 2 || page.Offset != 4 {
		t.Errorf("page = %+v", page)
	}
	if gotURL != "http://test/v1/billing/invoices?limit=2&offset=4" {
		t.Errorf("url = %s", gotURL)
	}
}

func TestBytesRoutes(t *testing.T) {
	c := testClient(t, func(r *http.Request) (*http.Response, error) {
		if strings.HasSuffix(r.URL.Path, "/nope/pdf") {
			return jsonResponse(404, `{"title":"not found"}`), nil
		}
		return &http.Response{
			StatusCode: 200,
			Header:     http.Header{"Content-Type": []string{"application/pdf"}},
			Body:       io.NopCloser(strings.NewReader("%PDF-1.7")),
		}, nil
	})
	pdf, err := c.Invoices().PDF(context.Background(), "inv1")
	if err != nil || string(pdf) != "%PDF-1.7" {
		t.Fatalf("pdf = %q err = %v", pdf, err)
	}
	var notFound *NotFoundError
	if _, err := c.Invoices().PDF(context.Background(), "nope"); !errors.As(err, &notFound) {
		t.Errorf("expected NotFoundError, got %v", err)
	}
}

func TestUploadIsMultipart(t *testing.T) {
	var contentType, body string
	c := testClient(t, func(r *http.Request) (*http.Response, error) {
		contentType = r.Header.Get("Content-Type")
		raw, _ := io.ReadAll(r.Body)
		body = string(raw)
		return jsonResponse(201, `{"id":"f1"}`), nil
	})
	if _, err := c.Files().Upload(context.Background(), "a.txt", []byte("hello"), "text/plain"); err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(contentType, "multipart/form-data; boundary=") {
		t.Errorf("content type = %s", contentType)
	}
	if !strings.Contains(body, `filename="a.txt"`) || !strings.Contains(body, "hello") {
		t.Errorf("body = %s", body)
	}
}

func TestPayloadShapes(t *testing.T) {
	type call struct{ method, path, query, body string }
	var calls []call
	c := testClient(t, func(r *http.Request) (*http.Response, error) {
		var raw []byte
		if r.Body != nil {
			raw, _ = io.ReadAll(r.Body)
		}
		calls = append(calls, call{r.Method, r.URL.Path, r.URL.RawQuery, string(raw)})
		if r.Method == "DELETE" || strings.HasSuffix(r.URL.Path, "/suspend") {
			return &http.Response{StatusCode: 204, Body: io.NopCloser(strings.NewReader(""))}, nil
		}
		return jsonResponse(200, `{}`), nil
	})
	ctx := context.Background()
	_, _ = c.Auth().Login(ctx, "a@b.c", "pw")
	_, _ = c.FeatureFlags().SetOverride(ctx, "k", map[string]any{"enabled": true, "organization_id": "o1"})
	_, _ = c.Roles().Update(ctx, "r1", map[string]any{"permissions": []string{"org:read"}})
	_, _ = c.Usage().Record(ctx, []UsageEvent{{Metric: "api_requests", Quantity: 2, IdempotencyKey: "k1"}})
	_, _ = c.Webhooks().ListDeliveries(ctx, Paging{Limit: 10}, "e1")
	_ = c.Admin().SuspendOrg(ctx, "org1")
	_ = c.Admin().RevokeGrant(ctx, "org1", "g1")
	want := []call{
		{"POST", "/v1/auth/login", "", `{"email":"a@b.c","password":"pw"}`},
		{"POST", "/v1/feature-flags/k/overrides", "", `{"enabled":true,"organization_id":"o1"}`},
		{"PATCH", "/v1/roles/r1", "", `{"permissions":["org:read"]}`},
		{"POST", "/v1/usage/events", "", `{"events":[{"metric":"api_requests","quantity":2,"idempotency_key":"k1"}]}`},
		{"GET", "/v1/webhooks/deliveries", "endpoint_id=e1&limit=10", ""},
		{"POST", "/v1/orgs/org1/suspend", "", ""},
		{"DELETE", "/v1/admin/orgs/org1/entitlements/grants/g1", "", ""},
	}
	if len(calls) != len(want) {
		t.Fatalf("calls = %+v", calls)
	}
	for i := range want {
		if calls[i] != want[i] {
			t.Errorf("call %d = %+v, want %+v", i, calls[i], want[i])
		}
	}
}
