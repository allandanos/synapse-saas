package synapse

import (
	"context"
	"encoding/json"
)

// jsonMap is the response shape for untyped endpoints.
type jsonMap = map[string]any

type AuthResource struct{ c *Client }

func (r *AuthResource) Me(ctx context.Context) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "GET", path: "/v1/auth/me"})
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

type EntitlementsResource struct{ c *Client }

func (r *EntitlementsResource) Effective(ctx context.Context) (jsonMap, error) {
	var out jsonMap
	raw, err := r.c.do(ctx, request{method: "GET", path: "/v1/entitlements"})
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
