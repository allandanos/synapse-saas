package synapse

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
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
func (c *Client) Auth() *AuthResource     { return &AuthResource{c} }
func (c *Client) Orgs() *OrgsResource     { return &OrgsResource{c} }
func (c *Client) Members() *MembersResource { return &MembersResource{c} }
func (c *Client) Subscription() *SubscriptionResource {
	return &SubscriptionResource{c}
}
func (c *Client) Usage() *UsageResource           { return &UsageResource{c} }
func (c *Client) Entitlements() *EntitlementsResource { return &EntitlementsResource{c} }
func (c *Client) APIKeys() *APIKeysResource       { return &APIKeysResource{c} }

// ── request core ─────────────────────────────────────────────────────────────

type request struct {
	method string
	path   string
	body   any
	params map[string]string
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

	var reader io.Reader
	if r.body != nil {
		encoded, err := json.Marshal(r.body)
		if err != nil {
			return nil, fmt.Errorf("synapse: encode body: %w", err)
		}
		reader = bytes.NewReader(encoded)
	}

	req, err := http.NewRequestWithContext(ctx, r.method, u, reader)
	if err != nil {
		return nil, fmt.Errorf("synapse: build request: %w", err)
	}
	for k, v := range c.header {
		req.Header.Set(k, v)
	}
	if r.body != nil {
		req.Header.Set("Content-Type", "application/json")
	}

	resp, err := c.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("synapse: request: %w", err)
	}
	defer resp.Body.Close()

	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("synapse: read body: %w", err)
	}
	if resp.StatusCode == http.StatusNoContent {
		return nil, nil
	}
	if resp.StatusCode >= 400 {
		return nil, errorFor(resp.StatusCode, raw)
	}
	return json.RawMessage(raw), nil
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
