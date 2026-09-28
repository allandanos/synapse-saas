package synapse

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"mime/multipart"
	"net/textproto"
	"strconv"
)

// jsonMap is the response shape for untyped endpoints.
type jsonMap = map[string]any

type AuthResource struct{ c *Client }

func (r *AuthResource) Me(ctx context.Context) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "GET", path: "/v1/auth/me"})
	return out, firstErr(decode(raw, &out), err)
}

func (r *AuthResource) Register(ctx context.Context, email, password, displayName string) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{
		method: "POST", path: "/v1/auth/register",
		body: map[string]string{"email": email, "password": password, "display_name": displayName},
	})
	return out, firstErr(decode(raw, &out), err)
}

// Login returns {user, tokens}; SSO-only accounts answer 401 with sso_url.
func (r *AuthResource) Login(ctx context.Context, email, password string) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{
		method: "POST", path: "/v1/auth/login", body: map[string]string{"email": email, "password": password},
	})
	return out, firstErr(decode(raw, &out), err)
}

func (r *AuthResource) Refresh(ctx context.Context, refreshToken string) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{
		method: "POST", path: "/v1/auth/refresh", body: map[string]string{"refresh_token": refreshToken},
	})
	return out, firstErr(decode(raw, &out), err)
}

func (r *AuthResource) Logout(ctx context.Context) error {
	_, err := r.c.do(ctx, request{method: "POST", path: "/v1/auth/logout"})
	return err
}

func (r *AuthResource) ForgotPassword(ctx context.Context, email string) error {
	_, err := r.c.do(ctx, request{method: "POST", path: "/v1/auth/forgot-password", body: map[string]string{"email": email}})
	return err
}

func (r *AuthResource) ResetPassword(ctx context.Context, token, password string) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{
		method: "POST", path: "/v1/auth/reset-password", body: map[string]string{"token": token, "password": password},
	})
	return out, firstErr(decode(raw, &out), err)
}

func (r *AuthResource) AcceptInvite(ctx context.Context, token string) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "POST", path: "/v1/auth/accept-invite", body: map[string]string{"token": token}})
	return out, firstErr(decode(raw, &out), err)
}

func (r *AuthResource) SwitchOrg(ctx context.Context, organizationID string) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{
		method: "POST", path: "/v1/auth/switch-org",
		body: map[string]string{"organization_id": organizationID},
	})
	return out, firstErr(decode(raw, &out), err)
}

type OrgsResource struct{ c *Client }

func (r *OrgsResource) List(ctx context.Context) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "GET", path: "/v1/orgs"})
	return out, firstErr(decode(raw, &out), err)
}

func (r *OrgsResource) Create(ctx context.Context, name string) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{
		method: "POST", path: "/v1/orgs", body: map[string]string{"name": name},
	})
	return out, firstErr(decode(raw, &out), err)
}

func (r *OrgsResource) Current(ctx context.Context) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "GET", path: "/v1/orgs/current"})
	return out, firstErr(decode(raw, &out), err)
}

type MembersResource struct{ c *Client }

func (r *MembersResource) List(ctx context.Context) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "GET", path: "/v1/orgs/current/members"})
	return out, firstErr(decode(raw, &out), err)
}

func (r *MembersResource) Invite(ctx context.Context, email string) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{
		method: "POST", path: "/v1/orgs/current/members/invite",
		body: map[string]any{"email": email, "role_keys": []string{"member"}},
	})
	return out, firstErr(decode(raw, &out), err)
}

func (r *MembersResource) Remove(ctx context.Context, membershipID string) error {
	_, err := r.c.do(ctx, request{method: "DELETE", path: "/v1/memberships/" + membershipID})
	return err
}

type SubscriptionResource struct{ c *Client }

// Current returns subscription + entitlements + usage in one call.
func (r *SubscriptionResource) Current(ctx context.Context) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "GET", path: "/v1/subscription"})
	return out, firstErr(decode(raw, &out), err)
}

func (r *SubscriptionResource) Plans(ctx context.Context) ([]jsonMap, error) {
	var out []jsonMap
	raw, err := r.c.do(ctx, request{method: "GET", path: "/v1/plans"})
	return out, firstErr(decode(raw, &out), err)
}

func (r *SubscriptionResource) Change(ctx context.Context, planKey string) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{
		method: "POST", path: "/v1/subscription/change",
		body: map[string]string{"plan_key": planKey},
	})
	return out, firstErr(decode(raw, &out), err)
}

func (r *SubscriptionResource) StartTrial(ctx context.Context, planKey string) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{
		method: "POST", path: "/v1/subscription/trial",
		body: map[string]string{"plan_key": planKey},
	})
	return out, firstErr(decode(raw, &out), err)
}

func (r *SubscriptionResource) Cancel(ctx context.Context, atPeriodEnd bool) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{
		method: "POST", path: "/v1/subscription/cancel",
		body: map[string]bool{"at_period_end": atPeriodEnd},
	})
	return out, firstErr(decode(raw, &out), err)
}

type UsageResource struct{ c *Client }

func (r *UsageResource) Summary(ctx context.Context) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "GET", path: "/v1/usage/summary"})
	return out, firstErr(decode(raw, &out), err)
}

// Consume meters + enforces: returns a LimitError (402) when the quota trips.
func (r *UsageResource) Consume(ctx context.Context, metric string, quantity int) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{
		method: "POST", path: "/v1/usage/consume",
		body: map[string]any{"events": []any{map[string]any{"metric": metric, "quantity": quantity}}},
	})
	return out, firstErr(decode(raw, &out), err)
}

// UsageEvent is one metered event for ConsumeBatch. IdempotencyKey is optional.
type UsageEvent struct {
	Metric         string `json:"metric"`
	Quantity       int    `json:"quantity"`
	IdempotencyKey string `json:"idempotency_key,omitempty"`
}

// ConsumeBatch is all-or-nothing: the first breach returns a LimitError and nothing is counted.
func (r *UsageResource) ConsumeBatch(ctx context.Context, events []UsageEvent) ([]jsonMap, error) {
	var out []jsonMap
	raw, err := r.c.do(ctx, request{
		method: "POST", path: "/v1/usage/consume-batch",
		body: map[string]any{"events": events},
	})
	return out, firstErr(decode(raw, &out), err)
}

// SetGauge sets a gauge metric (seats, projects, bytes stored) to an absolute level.
func (r *UsageResource) SetGauge(ctx context.Context, metric string, value int) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{
		method: "POST", path: "/v1/usage/gauge",
		body: map[string]any{"metric": metric, "value": value},
	})
	return out, firstErr(decode(raw, &out), err)
}

// AdjustGauge moves a gauge by delta (never below zero).
func (r *UsageResource) AdjustGauge(ctx context.Context, metric string, delta int) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{
		method: "POST", path: "/v1/usage/gauge",
		body: map[string]any{"metric": metric, "delta": delta},
	})
	return out, firstErr(decode(raw, &out), err)
}

type EntitlementsResource struct{ c *Client }

func (r *EntitlementsResource) Effective(ctx context.Context) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "GET", path: "/v1/entitlements"})
	return out, firstErr(decode(raw, &out), err)
}

// Grant creates a time-boxed feature grant (trial/promo/override/…)
// independent of the org's plan.
// Grant is a platform-operator action (platform-admin bearer): a time-boxed
// feature grant for any organization. Tenants cannot grant themselves entitlements.
func (r *EntitlementsResource) Grant(ctx context.Context, organizationID, featureKey, source string, durationDays int) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{
		method: "POST", path: "/v1/admin/orgs/" + organizationID + "/entitlements/grants",
		body: map[string]any{
			"feature_key":   featureKey,
			"source":        source,
			"duration_days": durationDays,
		},
	})
	return out, firstErr(decode(raw, &out), err)
}

type APIKeysResource struct{ c *Client }

// Create returns the plaintext key exactly once — persist it immediately.
func (r *APIKeysResource) Create(ctx context.Context, name string) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{
		method: "POST", path: "/v1/api-keys",
		body: map[string]any{"name": name, "scopes": []string{}},
	})
	return out, firstErr(decode(raw, &out), err)
}

func (r *APIKeysResource) Revoke(ctx context.Context, keyID string) error {
	_, err := r.c.do(ctx, request{method: "DELETE", path: "/v1/api-keys/" + keyID})
	return err
}

func firstErr(decodeErr, doErr error) error {
	if doErr != nil {
		return doErr
	}
	return decodeErr
}

var _ = json.RawMessage{}

// Update patches the current org (name and/or settings).
func (r *OrgsResource) Update(ctx context.Context, patch map[string]any) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "PATCH", path: "/v1/orgs/current", body: patch})
	return out, firstErr(decode(raw, &out), err)
}

// Update patches a membership: role_keys and/or status (active|suspended).
func (r *MembersResource) Update(ctx context.Context, membershipID string, patch map[string]any) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "PATCH", path: "/v1/memberships/" + membershipID, body: patch})
	return out, firstErr(decode(raw, &out), err)
}

func (r *SubscriptionResource) Resume(ctx context.Context) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "POST", path: "/v1/subscription/resume"})
	return out, firstErr(decode(raw, &out), err)
}

func (r *SubscriptionResource) PlansPage(ctx context.Context, paging Paging) (Page, error) {
	return r.c.page(ctx, "/v1/plans", paging, nil)
}

// Record meters without enforcing (never blocks). IdempotencyKey per event dedupes retries.
func (r *UsageResource) Record(ctx context.Context, events []UsageEvent) ([]jsonMap, error) {
	var out []jsonMap
	raw, err := r.c.do(ctx, request{method: "POST", path: "/v1/usage/events", body: map[string]any{"events": events}})
	return out, firstErr(decode(raw, &out), err)
}

// Check is the read-only pre-flight for a metric.
func (r *UsageResource) Check(ctx context.Context, metric string, quantity int) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{
		method: "GET", path: "/v1/usage/check",
		params: map[string]string{"metric": metric, "quantity": strconv.Itoa(quantity)},
	})
	return out, firstErr(decode(raw, &out), err)
}

type RolesResource struct{ c *Client }

func (r *RolesResource) List(ctx context.Context) ([]jsonMap, error) {
	var out []jsonMap
	raw, err := r.c.do(ctx, request{method: "GET", path: "/v1/roles"})
	return out, firstErr(decode(raw, &out), err)
}

// Permissions is the permission catalog (resource:action keys).
func (r *RolesResource) Permissions(ctx context.Context) ([]jsonMap, error) {
	var out []jsonMap
	raw, err := r.c.do(ctx, request{method: "GET", path: "/v1/permissions"})
	return out, firstErr(decode(raw, &out), err)
}

func (r *RolesResource) Create(ctx context.Context, key, name string, permissions []string) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{
		method: "POST", path: "/v1/roles",
		body: map[string]any{"key": key, "name": name, "permissions": permissions},
	})
	return out, firstErr(decode(raw, &out), err)
}

func (r *RolesResource) Update(ctx context.Context, roleID string, patch map[string]any) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "PATCH", path: "/v1/roles/" + roleID, body: patch})
	return out, firstErr(decode(raw, &out), err)
}

func (r *RolesResource) Delete(ctx context.Context, roleID string) error {
	_, err := r.c.do(ctx, request{method: "DELETE", path: "/v1/roles/" + roleID})
	return err
}

type BillingResource struct{ c *Client }

// Checkout returns {url} for hosted providers, or manual payment instructions.
func (r *BillingResource) Checkout(ctx context.Context, planKey string) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "POST", path: "/v1/billing/checkout", body: map[string]string{"plan_key": planKey}})
	return out, firstErr(decode(raw, &out), err)
}

// ConfirmCheckout is manual-provider only (409 checkout_confirm_not_allowed elsewhere).
func (r *BillingResource) ConfirmCheckout(ctx context.Context, planKey string) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "POST", path: "/v1/billing/checkout/confirm", body: map[string]string{"plan_key": planKey}})
	return out, firstErr(decode(raw, &out), err)
}

func (r *BillingResource) PortalURL(ctx context.Context) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "GET", path: "/v1/billing/portal-url"})
	return out, firstErr(decode(raw, &out), err)
}

func (r *BillingResource) SpendSummary(ctx context.Context) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "GET", path: "/v1/billing/spend-summary"})
	return out, firstErr(decode(raw, &out), err)
}

func (r *BillingResource) SpendMonthly(ctx context.Context) ([]jsonMap, error) {
	var out []jsonMap
	raw, err := r.c.do(ctx, request{method: "GET", path: "/v1/billing/spend-monthly"})
	return out, firstErr(decode(raw, &out), err)
}

type InvoicesResource struct{ c *Client }

func (r *InvoicesResource) List(ctx context.Context, paging Paging) (Page, error) {
	return r.c.page(ctx, "/v1/billing/invoices", paging, nil)
}

func (r *InvoicesResource) Get(ctx context.Context, invoiceID string) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "GET", path: "/v1/billing/invoices/" + invoiceID})
	return out, firstErr(decode(raw, &out), err)
}

// PDF returns the framework-rendered invoice PDF bytes.
func (r *InvoicesResource) PDF(ctx context.Context, invoiceID string) ([]byte, error) {
	return r.c.bytes(ctx, "/v1/billing/invoices/"+invoiceID+"/pdf")
}

// Draft creates (or returns) the period invoice; period is "YYYY-MM" or "" for the current one.
func (r *InvoicesResource) Draft(ctx context.Context, period string) (jsonMap, error) {
	body := map[string]any{}
	if period != "" {
		body["period"] = period
	}
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "POST", path: "/v1/billing/invoices/draft", body: body})
	return out, firstErr(decode(raw, &out), err)
}

func (r *InvoicesResource) Finalize(ctx context.Context, invoiceID string) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "POST", path: "/v1/billing/invoices/" + invoiceID + "/finalize"})
	return out, firstErr(decode(raw, &out), err)
}

type WebhooksResource struct{ c *Client }

func (r *WebhooksResource) ListEndpoints(ctx context.Context, paging Paging) (Page, error) {
	return r.c.page(ctx, "/v1/webhooks/endpoints", paging, nil)
}

// CreateEndpoint registers a URL; the signing secret is returned exactly once. Empty events ⇒ all.
func (r *WebhooksResource) CreateEndpoint(ctx context.Context, url string, events []string) (jsonMap, error) {
	if events == nil {
		events = []string{}
	}
	var out jsonMap
	raw, err := r.c.do(ctx, request{
		method: "POST", path: "/v1/webhooks/endpoints", body: map[string]any{"url": url, "events": events},
	})
	return out, firstErr(decode(raw, &out), err)
}

func (r *WebhooksResource) DeleteEndpoint(ctx context.Context, endpointID string) error {
	_, err := r.c.do(ctx, request{method: "DELETE", path: "/v1/webhooks/endpoints/" + endpointID})
	return err
}

func (r *WebhooksResource) ListDeliveries(ctx context.Context, paging Paging, endpointID string) (Page, error) {
	return r.c.page(ctx, "/v1/webhooks/deliveries", paging, map[string]string{"endpoint_id": endpointID})
}

func (r *WebhooksResource) RetryDelivery(ctx context.Context, deliveryID string) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "POST", path: "/v1/webhooks/deliveries/" + deliveryID + "/retry"})
	return out, firstErr(decode(raw, &out), err)
}

type FilesResource struct{ c *Client }

func (r *FilesResource) List(ctx context.Context, paging Paging) (Page, error) {
	return r.c.page(ctx, "/v1/files", paging, nil)
}

// Upload is the direct multipart path (≤10 MiB). Larger objects: PresignUpload + Complete.
func (r *FilesResource) Upload(ctx context.Context, name string, content []byte, contentType string) (jsonMap, error) {
	var buf bytes.Buffer
	w := multipart.NewWriter(&buf)
	h := textproto.MIMEHeader{}
	h.Set("Content-Disposition", fmt.Sprintf(`form-data; name="file"; filename="%s"`, name))
	if contentType == "" {
		contentType = "application/octet-stream"
	}
	h.Set("Content-Type", contentType)
	part, err := w.CreatePart(h)
	if err != nil {
		return nil, err
	}
	if _, err := part.Write(content); err != nil {
		return nil, err
	}
	if err := w.Close(); err != nil {
		return nil, err
	}
	var out jsonMap
	raw, err := r.c.do(ctx, request{
		method: "POST", path: "/v1/files", rawBody: &buf, rawContentType: w.FormDataContentType(),
	})
	return out, firstErr(decode(raw, &out), err)
}

func (r *FilesResource) Download(ctx context.Context, fileID string) ([]byte, error) {
	return r.c.bytes(ctx, "/v1/files/"+fileID)
}

func (r *FilesResource) PresignDownload(ctx context.Context, fileID string) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "POST", path: "/v1/files/" + fileID + "/presign"})
	return out, firstErr(decode(raw, &out), err)
}

// PresignUpload returns {id, url, method, headers, expires_in}: PUT the bytes there, then Complete(id).
func (r *FilesResource) PresignUpload(ctx context.Context, name string, sizeBytes int64, contentType string) (jsonMap, error) {
	if contentType == "" {
		contentType = "application/octet-stream"
	}
	var out jsonMap
	raw, err := r.c.do(ctx, request{
		method: "POST", path: "/v1/files/presign-upload",
		body: map[string]any{"name": name, "size_bytes": sizeBytes, "content_type": contentType},
	})
	return out, firstErr(decode(raw, &out), err)
}

func (r *FilesResource) Complete(ctx context.Context, fileID string) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "POST", path: "/v1/files/" + fileID + "/complete"})
	return out, firstErr(decode(raw, &out), err)
}

func (r *FilesResource) Delete(ctx context.Context, fileID string) error {
	_, err := r.c.do(ctx, request{method: "DELETE", path: "/v1/files/" + fileID})
	return err
}

type FeatureFlagsResource struct{ c *Client }

// Check resolves a flag for the caller's org + user: {key, enabled}.
func (r *FeatureFlagsResource) Check(ctx context.Context, key string) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "GET", path: "/v1/feature-flags/check/" + key})
	return out, firstErr(decode(raw, &out), err)
}

// Platform-admin surface.
func (r *FeatureFlagsResource) List(ctx context.Context, paging Paging) (Page, error) {
	return r.c.page(ctx, "/v1/feature-flags", paging, nil)
}

func (r *FeatureFlagsResource) Create(ctx context.Context, body map[string]any) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "POST", path: "/v1/feature-flags", body: body})
	return out, firstErr(decode(raw, &out), err)
}

func (r *FeatureFlagsResource) Update(ctx context.Context, key string, patch map[string]any) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "PATCH", path: "/v1/feature-flags/" + key, body: patch})
	return out, firstErr(decode(raw, &out), err)
}

func (r *FeatureFlagsResource) ListOverrides(ctx context.Context, key string) ([]jsonMap, error) {
	var out []jsonMap
	raw, err := r.c.do(ctx, request{method: "GET", path: "/v1/feature-flags/" + key + "/overrides"})
	return out, firstErr(decode(raw, &out), err)
}

func (r *FeatureFlagsResource) SetOverride(ctx context.Context, key string, body map[string]any) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "POST", path: "/v1/feature-flags/" + key + "/overrides", body: body})
	return out, firstErr(decode(raw, &out), err)
}

func (r *FeatureFlagsResource) DeleteOverride(ctx context.Context, overrideID string) error {
	_, err := r.c.do(ctx, request{method: "DELETE", path: "/v1/feature-flags/overrides/" + overrideID})
	return err
}

// AgentsResource: registry + governance (ADR 0007); every call is behind the agents feature.
type AgentsResource struct{ c *Client }

func (r *AgentsResource) List(ctx context.Context, paging Paging) (Page, error) {
	return r.c.page(ctx, "/v1/agents", paging, nil)
}

func (r *AgentsResource) Create(ctx context.Context, slug, name string, config map[string]any) (jsonMap, error) {
	if config == nil {
		config = map[string]any{}
	}
	var out jsonMap
	raw, err := r.c.do(ctx, request{
		method: "POST", path: "/v1/agents", body: map[string]any{"slug": slug, "name": name, "config": config},
	})
	return out, firstErr(decode(raw, &out), err)
}

func (r *AgentsResource) Get(ctx context.Context, agentID string) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "GET", path: "/v1/agents/" + agentID})
	return out, firstErr(decode(raw, &out), err)
}

func (r *AgentsResource) Update(ctx context.Context, agentID string, patch map[string]any) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "PATCH", path: "/v1/agents/" + agentID, body: patch})
	return out, firstErr(decode(raw, &out), err)
}

func (r *AgentsResource) Delete(ctx context.Context, agentID string) error {
	_, err := r.c.do(ctx, request{method: "DELETE", path: "/v1/agents/" + agentID})
	return err
}

func (r *AgentsResource) Enable(ctx context.Context, agentID string) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "POST", path: "/v1/agents/" + agentID + "/enable"})
	return out, firstErr(decode(raw, &out), err)
}

func (r *AgentsResource) Disable(ctx context.Context, agentID string) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "POST", path: "/v1/agents/" + agentID + "/disable"})
	return out, firstErr(decode(raw, &out), err)
}

type AuditResource struct{ c *Client }

func (r *AuditResource) List(ctx context.Context, paging Paging, filters map[string]string) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "GET", path: "/v1/audit", params: paging.params(filters)})
	return out, firstErr(decode(raw, &out), err)
}

// AdminResource is the platform-operator surface (platform-admin bearer, explicit org ids) — ADR 0008.
type AdminResource struct{ c *Client }

func (r *AdminResource) Entitlements(ctx context.Context, organizationID string) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "GET", path: "/v1/admin/orgs/" + organizationID + "/entitlements"})
	return out, firstErr(decode(raw, &out), err)
}

func (r *AdminResource) Grant(ctx context.Context, organizationID string, body map[string]any) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{
		method: "POST", path: "/v1/admin/orgs/" + organizationID + "/entitlements/grants", body: body,
	})
	return out, firstErr(decode(raw, &out), err)
}

func (r *AdminResource) RevokeGrant(ctx context.Context, organizationID, grantID string) error {
	_, err := r.c.do(ctx, request{
		method: "DELETE", path: "/v1/admin/orgs/" + organizationID + "/entitlements/grants/" + grantID,
	})
	return err
}

func (r *AdminResource) PayInvoice(ctx context.Context, invoiceID string, amountCents int64, reference string) (jsonMap, error) {
	body := map[string]any{"amount_cents": amountCents}
	if reference != "" {
		body["reference"] = reference
	}
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "POST", path: "/v1/billing/admin/invoices/" + invoiceID + "/pay", body: body})
	return out, firstErr(decode(raw, &out), err)
}

func (r *AdminResource) VoidInvoice(ctx context.Context, invoiceID string) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "POST", path: "/v1/billing/admin/invoices/" + invoiceID + "/void"})
	return out, firstErr(decode(raw, &out), err)
}

func (r *AdminResource) RevenueSummary(ctx context.Context) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "GET", path: "/v1/billing/admin/revenue-summary"})
	return out, firstErr(decode(raw, &out), err)
}

func (r *AdminResource) RevenueMonthly(ctx context.Context) ([]jsonMap, error) {
	var out []jsonMap
	raw, err := r.c.do(ctx, request{method: "GET", path: "/v1/billing/admin/revenue-monthly"})
	return out, firstErr(decode(raw, &out), err)
}

func (r *AdminResource) SuspendOrg(ctx context.Context, organizationID string) error {
	_, err := r.c.do(ctx, request{method: "POST", path: "/v1/orgs/" + organizationID + "/suspend"})
	return err
}

func (r *AdminResource) UnsuspendOrg(ctx context.Context, organizationID string) error {
	_, err := r.c.do(ctx, request{method: "DELETE", path: "/v1/orgs/" + organizationID + "/suspend"})
	return err
}

// List pages the org's keys (never the secrets: those are shown once at Create).
func (r *APIKeysResource) List(ctx context.Context, paging Paging) (Page, error) {
	return r.c.page(ctx, "/v1/api-keys", paging, nil)
}
