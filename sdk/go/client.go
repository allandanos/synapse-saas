package synapse

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"time"
)

// Options configures a Client.
type Options struct {
	APIKey      string // sk_… programmatic access
	AccessToken string // user-session JWT
	OrgID       string // X-Org-Id header (unused for API-key org pinning)
	Timeout     time.Duration
	HTTPClient  *http.Client // test seam
}

// Client is the Synapse API client. Safe for concurrent use.
type Client struct {
	base   string
	header map[string]string
	http   *http.Client
}

// New builds a client. Exactly one of apiKey/accessToken is required.
func New(baseURL string, opts Options) (*Client, error) {
	if opts.APIKey == "" && opts.AccessToken == "" {
		return nil, fmt.Errorf("synapse: APIKey or AccessToken is required")
	}
	token := opts.APIKey
	if token == "" {
		token = opts.AccessToken
	}
	header := map[string]string{"Authorization": "Bearer " + token}
	if opts.OrgID != "" {
		header["X-Org-Id"] = opts.OrgID
	}
	timeout := opts.Timeout
	if timeout == 0 {
		timeout = 30 * time.Second
	}
	hc := opts.HTTPClient
	if hc == nil {
		hc = &http.Client{Timeout: timeout}
	}
	return &Client{base: trimSlash(baseURL), header: header, http: hc}, nil
}

// Auth resources.
func (c *Client) Auth() *AuthResource       { return &AuthResource{c} }
func (c *Client) Orgs() *OrgsResource       { return &OrgsResource{c} }
func (c *Client) Members() *MembersResource { return &MembersResource{c} }
func (c *Client) Subscription() *SubscriptionResource {
	return &SubscriptionResource{c}
}
func (c *Client) Usage() *UsageResource               { return &UsageResource{c} }
func (c *Client) Entitlements() *EntitlementsResource { return &EntitlementsResource{c} }
func (c *Client) APIKeys() *APIKeysResource           { return &APIKeysResource{c} }
func (c *Client) Roles() *RolesResource               { return &RolesResource{c} }
func (c *Client) Billing() *BillingResource           { return &BillingResource{c} }
func (c *Client) Invoices() *InvoicesResource         { return &InvoicesResource{c} }
func (c *Client) Webhooks() *WebhooksResource         { return &WebhooksResource{c} }
func (c *Client) Files() *FilesResource               { return &FilesResource{c} }
func (c *Client) FeatureFlags() *FeatureFlagsResource { return &FeatureFlagsResource{c} }
func (c *Client) Agents() *AgentsResource             { return &AgentsResource{c} }
func (c *Client) Audit() *AuditResource               { return &AuditResource{c} }
func (c *Client) Admin() *AdminResource               { return &AdminResource{c} }

// Meta: framework version, active billing/identity providers, tenant isolation mode.
func (c *Client) Meta(ctx context.Context) (jsonMap, error) {
	var out jsonMap
	raw, err := c.do(ctx, request{method: "GET", path: "/v1/meta"})
	return out, firstErr(decode(raw, &out), err)
}

// Page is one page of a list route: the items plus the server's total (X-Total-Count).
type Page struct {
	Items  []jsonMap
	Total  int
	Limit  int
	Offset int
}

// Paging selects a page of a list route.
type Paging struct {
	Limit  int
	Offset int
}

func (p Paging) params(extra map[string]string) map[string]string {
	out := map[string]string{}
	for k, v := range extra {
		if v != "" {
			out[k] = v
		}
	}
	if p.Limit > 0 {
		out["limit"] = strconv.Itoa(p.Limit)
	}
	if p.Offset > 0 {
		out["offset"] = strconv.Itoa(p.Offset)
	}
	return out
}

// ── request core ─────────────────────────────────────────────────────────────

type request struct {
	method string
	path   string
	body   any
	params map[string]string
	// multipart upload: when set, sent as the body with this content type
	rawBody        io.Reader
	rawContentType string
}

func (c *Client) do(ctx context.Context, r request) (json.RawMessage, error) {
	u := c.base + r.path
	if len(r.params) > 0 {
		q := url.Values{}
		for k, v := range r.params {
			q.Set(k, v)
		}
		u += "?" + q.Encode()
	}

	raw, _, err := c.doFull(ctx, r)
	return raw, err
}

// doFull is do plus the response headers (list routes carry X-Total-Count).
func (c *Client) doFull(ctx context.Context, r request) (json.RawMessage, http.Header, error) {
	u := c.base + r.path
	if len(r.params) > 0 {
		q := url.Values{}
		for k, v := range r.params {
			q.Set(k, v)
		}
		u += "?" + q.Encode()
	}

	var reader io.Reader
	contentType := ""
	switch {
	case r.rawBody != nil:
		reader = r.rawBody
		contentType = r.rawContentType
	case r.body != nil:
		encoded, err := json.Marshal(r.body)
		if err != nil {
			return nil, nil, fmt.Errorf("synapse: encode body: %w", err)
		}
		reader = bytes.NewReader(encoded)
		contentType = "application/json"
	}

	req, err := http.NewRequestWithContext(ctx, r.method, u, reader)
	if err != nil {
		return nil, nil, fmt.Errorf("synapse: build request: %w", err)
	}
	for k, v := range c.header {
		req.Header.Set(k, v)
	}
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}

	resp, err := c.http.Do(req)
	if err != nil {
		return nil, nil, fmt.Errorf("synapse: request: %w", err)
	}
	defer resp.Body.Close()

	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, nil, fmt.Errorf("synapse: read body: %w", err)
	}
	if resp.StatusCode == http.StatusNoContent {
		return nil, resp.Header, nil
	}
	if resp.StatusCode >= 400 {
		return nil, resp.Header, errorFor(resp.StatusCode, raw)
	}
	return json.RawMessage(raw), resp.Header, nil
}

// page runs a GET list route and returns the items with the server total.
func (c *Client) page(ctx context.Context, path string, paging Paging, extra map[string]string) (Page, error) {
	raw, header, err := c.doFull(ctx, request{method: "GET", path: path, params: paging.params(extra)})
	if err != nil {
		return Page{}, err
	}
	var items []jsonMap
	if err := decode(raw, &items); err != nil {
		return Page{}, err
	}
	total := len(items)
	if v := header.Get("X-Total-Count"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			total = n
		}
	}
	return Page{Items: items, Total: total, Limit: paging.Limit, Offset: paging.Offset}, nil
}

// bytes runs a GET route whose body is not JSON (PDF, file download).
func (c *Client) bytes(ctx context.Context, path string) ([]byte, error) {
	raw, _, err := c.doFull(ctx, request{method: "GET", path: path})
	if err != nil {
		return nil, err
	}
	return []byte(raw), nil
}

func decode(raw json.RawMessage, out any) error {
	if out == nil || len(raw) == 0 {
		return nil
	}
	return json.Unmarshal(raw, out)
}

func trimSlash(s string) string {
	for len(s) > 0 && s[len(s)-1] == '/' {
		s = s[:len(s)-1]
	}
	return s
}
