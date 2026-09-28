import { errorFor, type Problem } from "./errors.js";

type Json = Record<string, unknown>;

/** One page of a list route: the items plus the server's total (`X-Total-Count`). */
export interface Page<T = Json> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface Paging {
  limit?: number;
  offset?: number;
  [param: string]: string | number | undefined;
}

interface RequestOptions {
  method?: string;
  body?: Json;
  params?: Record<string, string | number | undefined>;
  headers?: Record<string, string>;
  /** Raw multipart body (file uploads): sent as-is, no JSON content type. */
  form?: FormData;
}

export interface SynapseClientOptions {
  apiKey?: string;
  accessToken?: string;
  orgId?: string;
  timeoutMs?: number;
  /** Test seam: custom fetch. */
  fetchImpl?: typeof fetch;
}

export class SynapseClient {
  private readonly baseUrl: string;
  private readonly headers: Record<string, string>;
  private readonly timeoutMs: number;
  private readonly fetchImpl: typeof fetch;

  readonly auth = {
    me: (): Promise<Json> => this.call("GET", "/v1/auth/me"),
    switchOrg: (organizationId: string): Promise<Json> =>
      this.call("POST", "/v1/auth/switch-org", { body: { organization_id: organizationId } }),
    register: (email: string, password: string, displayName: string): Promise<Json> =>
      this.call("POST", "/v1/auth/register", { body: { email, password, display_name: displayName } }),
    /** `{user, tokens}`; SSO-only accounts answer 401 with `sso_url`. */
    login: (email: string, password: string): Promise<Json> =>
      this.call("POST", "/v1/auth/login", { body: { email, password } }),
    refresh: (refreshToken: string): Promise<Json> =>
      this.call("POST", "/v1/auth/refresh", { body: { refresh_token: refreshToken } }),
    logout: async (): Promise<void> => {
      await this.call("POST", "/v1/auth/logout");
    },
    forgotPassword: async (email: string): Promise<void> => {
      await this.call("POST", "/v1/auth/forgot-password", { body: { email } });
    },
    resetPassword: (token: string, password: string): Promise<Json> =>
      this.call("POST", "/v1/auth/reset-password", { body: { token, password } }),
    acceptInvite: (token: string): Promise<Json> =>
      this.call("POST", "/v1/auth/accept-invite", { body: { token } }),
  };

  /** Framework version, active billing/identity providers, tenant isolation mode. */
  meta = (): Promise<Json> => this.call("GET", "/v1/meta");

  readonly orgs = {
    list: (): Promise<Json> => this.call("GET", "/v1/orgs"),
    create: (name: string, slug?: string): Promise<Json> =>
      this.call("POST", "/v1/orgs", { body: { name, slug } }),
    current: (): Promise<Json> => this.call("GET", "/v1/orgs/current"),
    update: (patch: { name?: string; settings?: Json }): Promise<Json> =>
      this.call("PATCH", "/v1/orgs/current", { body: patch as Json }),
  };

  readonly members = {
    list: (): Promise<Json> => this.call("GET", "/v1/orgs/current/members"),
    invite: (email: string, roleKeys: string[] = ["member"]): Promise<Json> =>
      this.call("POST", "/v1/orgs/current/members/invite", {
        body: { email, role_keys: roleKeys },
      }),
    remove: async (membershipId: string): Promise<void> => {
      await this.call("DELETE", `/v1/memberships/${membershipId}`);
    },
    update: (membershipId: string, patch: { roleKeys?: string[]; status?: "active" | "suspended" }): Promise<Json> =>
      this.call("PATCH", `/v1/memberships/${membershipId}`, {
        body: { ...(patch.roleKeys && { role_keys: patch.roleKeys }), ...(patch.status && { status: patch.status }) },
      }),
  };

  readonly roles = {
    list: (): Promise<Json[]> => this.call("GET", "/v1/roles"),
    /** The permission catalog (`resource:action` keys). */
    permissions: (): Promise<Json[]> => this.call("GET", "/v1/permissions"),
    create: (key: string, name: string, permissions: string[], description?: string): Promise<Json> =>
      this.call("POST", "/v1/roles", { body: { key, name, permissions, ...(description && { description }) } }),
    update: (roleId: string, patch: { name?: string; description?: string; permissions?: string[] }): Promise<Json> =>
      this.call("PATCH", `/v1/roles/${roleId}`, { body: patch as Json }),
    delete: async (roleId: string): Promise<void> => {
      await this.call("DELETE", `/v1/roles/${roleId}`);
    },
  };

  readonly subscription = {
    /** Subscription + entitlements + usage snapshot in one call. */
    current: (): Promise<Json> => this.call("GET", "/v1/subscription"),
    plans: (): Promise<Json> => this.call("GET", "/v1/plans"),
    change: (planKey: string): Promise<Json> =>
      this.call("POST", "/v1/subscription/change", { body: { plan_key: planKey } }),
    startTrial: (planKey: string): Promise<Json> =>
      this.call("POST", "/v1/subscription/trial", { body: { plan_key: planKey } }),
    cancel: (atPeriodEnd = true): Promise<Json> =>
      this.call("POST", "/v1/subscription/cancel", { body: { at_period_end: atPeriodEnd } }),
    resume: (): Promise<Json> => this.call("POST", "/v1/subscription/resume"),
    plansPage: (paging: Paging = {}): Promise<Page> => this.callPage("/v1/plans", paging),
  };

  readonly billing = {
    /** `{url}` for hosted providers, or manual payment instructions. */
    checkout: (planKey: string): Promise<Json> =>
      this.call("POST", "/v1/billing/checkout", { body: { plan_key: planKey } }),
    /** Manual provider only (409 `checkout_confirm_not_allowed` elsewhere). */
    confirmCheckout: (planKey: string): Promise<Json> =>
      this.call("POST", "/v1/billing/checkout/confirm", { body: { plan_key: planKey } }),
    portalUrl: (): Promise<Json> => this.call("GET", "/v1/billing/portal-url"),
    spendSummary: (): Promise<Json> => this.call("GET", "/v1/billing/spend-summary"),
    spendMonthly: (): Promise<Json[]> => this.call("GET", "/v1/billing/spend-monthly"),
  };

  readonly invoices = {
    list: (paging: Paging = {}): Promise<Json[]> => this.call("GET", "/v1/billing/invoices", { params: paging }),
    listPage: (paging: Paging = {}): Promise<Page> => this.callPage("/v1/billing/invoices", paging),
    get: (invoiceId: string): Promise<Json> => this.call("GET", `/v1/billing/invoices/${invoiceId}`),
    pdf: (invoiceId: string): Promise<ArrayBuffer> => this.callBytes(`/v1/billing/invoices/${invoiceId}/pdf`),
    /** Draft (or return) the period invoice: plan + overage + prorated adjustments. */
    draft: (period?: string): Promise<Json> =>
      this.call("POST", "/v1/billing/invoices/draft", { body: period ? { period } : {} }),
    finalize: (invoiceId: string): Promise<Json> =>
      this.call("POST", `/v1/billing/invoices/${invoiceId}/finalize`),
  };

  readonly webhooks = {
    listEndpoints: (paging: Paging = {}): Promise<Json[]> =>
      this.call("GET", "/v1/webhooks/endpoints", { params: paging }),
    /** The signing `secret` is returned exactly once. */
    createEndpoint: (url: string, opts: { events?: string[]; description?: string } = {}): Promise<Json> =>
      this.call("POST", "/v1/webhooks/endpoints", {
        body: { url, events: opts.events ?? [], ...(opts.description && { description: opts.description }) },
      }),
    deleteEndpoint: async (endpointId: string): Promise<void> => {
      await this.call("DELETE", `/v1/webhooks/endpoints/${endpointId}`);
    },
    listDeliveries: (opts: Paging & { endpointId?: string } = {}): Promise<Json[]> =>
      this.call("GET", "/v1/webhooks/deliveries", {
        params: { limit: opts.limit, offset: opts.offset, endpoint_id: opts.endpointId },
      }),
    retryDelivery: (deliveryId: string): Promise<Json> =>
      this.call("POST", `/v1/webhooks/deliveries/${deliveryId}/retry`),
  };

  readonly files = {
    list: (paging: Paging = {}): Promise<Json[]> => this.call("GET", "/v1/files", { params: paging }),
    listPage: (paging: Paging = {}): Promise<Page> => this.callPage("/v1/files", paging),
    /** Direct multipart upload (≤10 MiB). Larger objects: presignUpload + complete. */
    upload: (name: string, content: Blob | Uint8Array, contentType = "application/octet-stream"): Promise<Json> => {
      const form = new FormData();
      const blob = content instanceof Blob ? content : new Blob([content as BlobPart], { type: contentType });
      form.append("file", blob, name);
      return this.call("POST", "/v1/files", { form });
    },
    download: (fileId: string): Promise<ArrayBuffer> => this.callBytes(`/v1/files/${fileId}`),
    presignDownload: (fileId: string): Promise<Json> => this.call("POST", `/v1/files/${fileId}/presign`),
    /** `{id, url, method, headers, expires_in}` — PUT the bytes there, then complete(id). */
    presignUpload: (name: string, sizeBytes: number, contentType = "application/octet-stream"): Promise<Json> =>
      this.call("POST", "/v1/files/presign-upload", {
        body: { name, size_bytes: sizeBytes, content_type: contentType },
      }),
    complete: (fileId: string): Promise<Json> => this.call("POST", `/v1/files/${fileId}/complete`),
    delete: async (fileId: string): Promise<void> => {
      await this.call("DELETE", `/v1/files/${fileId}`);
    },
  };

  readonly featureFlags = {
    /** `{key, enabled}` for the caller's org + user (overrides + rollout aware). */
    check: (key: string): Promise<Json> => this.call("GET", `/v1/feature-flags/check/${key}`),
    // Platform-admin surface
    list: (paging: Paging = {}): Promise<Json[]> => this.call("GET", "/v1/feature-flags", { params: paging }),
    create: (
      key: string,
      name: string,
      opts: { description?: string; enabled?: boolean; rolloutPercentage?: number } = {},
    ): Promise<Json> =>
      this.call("POST", "/v1/feature-flags", {
        body: {
          key,
          name,
          enabled: opts.enabled ?? false,
          ...(opts.description && { description: opts.description }),
          ...(opts.rolloutPercentage !== undefined && { rollout_percentage: opts.rolloutPercentage }),
        },
      }),
    update: (key: string, patch: { enabled?: boolean; rolloutPercentage?: number }): Promise<Json> =>
      this.call("PATCH", `/v1/feature-flags/${key}`, {
        body: {
          ...(patch.enabled !== undefined && { enabled: patch.enabled }),
          ...(patch.rolloutPercentage !== undefined && { rollout_percentage: patch.rolloutPercentage }),
        },
      }),
    listOverrides: (key: string): Promise<Json[]> => this.call("GET", `/v1/feature-flags/${key}/overrides`),
    setOverride: (
      key: string,
      opts: { enabled: boolean; organizationId?: string; userId?: string; note?: string },
    ): Promise<Json> =>
      this.call("POST", `/v1/feature-flags/${key}/overrides`, {
        body: {
          enabled: opts.enabled,
          ...(opts.organizationId && { organization_id: opts.organizationId }),
          ...(opts.userId && { user_id: opts.userId }),
          ...(opts.note && { note: opts.note }),
        },
      }),
    deleteOverride: async (overrideId: string): Promise<void> => {
      await this.call("DELETE", `/v1/feature-flags/overrides/${overrideId}`);
    },
  };

  /** Registry + governance (ADR 0007); every call is behind the `agents` feature. */
  readonly agents = {
    list: (paging: Paging = {}): Promise<Json[]> => this.call("GET", "/v1/agents", { params: paging }),
    create: (slug: string, name: string, opts: { description?: string; config?: Json } = {}): Promise<Json> =>
      this.call("POST", "/v1/agents", {
        body: { slug, name, config: opts.config ?? {}, ...(opts.description && { description: opts.description }) },
      }),
    get: (agentId: string): Promise<Json> => this.call("GET", `/v1/agents/${agentId}`),
    update: (agentId: string, patch: { name?: string; description?: string; config?: Json }): Promise<Json> =>
      this.call("PATCH", `/v1/agents/${agentId}`, { body: patch as Json }),
    delete: async (agentId: string): Promise<void> => {
      await this.call("DELETE", `/v1/agents/${agentId}`);
    },
    enable: (agentId: string): Promise<Json> => this.call("POST", `/v1/agents/${agentId}/enable`),
    disable: (agentId: string): Promise<Json> => this.call("POST", `/v1/agents/${agentId}/disable`),
  };

  readonly audit = {
    list: (opts: Paging & Record<string, string | number | undefined> = {}): Promise<Json> =>
      this.call("GET", "/v1/audit", { params: opts }),
  };

  /** Platform-operator surface (platform-admin bearer, explicit org ids) — ADR 0008. */
  readonly admin = {
    entitlements: (organizationId: string): Promise<Json> =>
      this.call("GET", `/v1/admin/orgs/${organizationId}/entitlements`),
    grant: (organizationId: string, body: Json): Promise<Json> =>
      this.call("POST", `/v1/admin/orgs/${organizationId}/entitlements/grants`, { body }),
    revokeGrant: async (organizationId: string, grantId: string): Promise<void> => {
      await this.call("DELETE", `/v1/admin/orgs/${organizationId}/entitlements/grants/${grantId}`);
    },
    payInvoice: (invoiceId: string, amountCents: number, reference?: string): Promise<Json> =>
      this.call("POST", `/v1/billing/admin/invoices/${invoiceId}/pay`, {
        body: { amount_cents: amountCents, ...(reference && { reference }) },
      }),
    voidInvoice: (invoiceId: string): Promise<Json> =>
      this.call("POST", `/v1/billing/admin/invoices/${invoiceId}/void`),
    revenueSummary: (): Promise<Json> => this.call("GET", "/v1/billing/admin/revenue-summary"),
    revenueMonthly: (): Promise<Json[]> => this.call("GET", "/v1/billing/admin/revenue-monthly"),
    suspendOrg: async (organizationId: string): Promise<void> => {
      await this.call("POST", `/v1/orgs/${organizationId}/suspend`);
    },
    unsuspendOrg: async (organizationId: string): Promise<void> => {
      await this.call("DELETE", `/v1/orgs/${organizationId}/suspend`);
    },
  };

  readonly usage = {
    summary: (period?: string): Promise<Json> =>
      this.call("GET", "/v1/usage/summary", { params: { period } }),
    check: (metric: string, quantity = 1): Promise<Json> =>
      this.call("GET", "/v1/usage/check", { params: { metric, quantity } }),
    consume: (metric: string, quantity = 1, opts: { idempotencyKey?: string } = {}): Promise<Json> =>
      this.call("POST", "/v1/usage/consume", {
        body: { events: [{ metric, quantity, idempotency_key: opts.idempotencyKey }] },
      }),
    /** All-or-nothing: the first breach 402s and nothing in the batch is counted. */
    consumeBatch: (
      events: { metric: string; quantity?: number; idempotencyKey?: string }[],
    ): Promise<Json> =>
      this.call("POST", "/v1/usage/consume-batch", {
        body: {
          events: events.map((e) => ({
            metric: e.metric,
            quantity: e.quantity ?? 1,
            idempotency_key: e.idempotencyKey,
          })),
        },
      }),
    /** Meter without enforcing (never blocks). `idempotencyKey` per event dedupes retries. */
    record: (events: { metric: string; quantity?: number; idempotencyKey?: string }[]): Promise<Json[]> =>
      this.call("POST", "/v1/usage/events", {
        body: {
          events: events.map((e) => ({ metric: e.metric, quantity: e.quantity ?? 1, idempotency_key: e.idempotencyKey })),
        },
      }),
    /** Gauges are levels (seats, projects, bytes): set an absolute value. */
    setGauge: (metric: string, value: number): Promise<Json> =>
      this.call("POST", "/v1/usage/gauge", { body: { metric, value } }),
    /** Move a gauge by delta (never below zero). */
    adjustGauge: (metric: string, delta: number): Promise<Json> =>
      this.call("POST", "/v1/usage/gauge", { body: { metric, delta } }),
  };

  readonly entitlements = {
    effective: (): Promise<Json> => this.call("GET", "/v1/entitlements"),
    /** Platform-operator action: requires a platform-admin bearer, targets any org. */
    grant: (
      organizationId: string,
      featureKey: string,
      source: string,
      opts: { durationDays?: number; limitValue?: number } = {},
    ): Promise<Json> =>
      this.call("POST", `/v1/admin/orgs/${organizationId}/entitlements/grants`, {
        body: {
          feature_key: featureKey,
          source,
          ...(opts.durationDays !== undefined && { duration_days: opts.durationDays }),
          ...(opts.limitValue !== undefined && { limit_value: opts.limitValue }),
        },
      }),
  };

  readonly apiKeys = {
    list: (): Promise<Json> => this.call("GET", "/v1/api-keys"),
    /** Returns the plaintext key exactly once — persist it immediately. */
    create: (name: string, scopes: string[] = [], expiresInDays?: number): Promise<Json> =>
      this.call("POST", "/v1/api-keys", {
        body: { name, scopes, ...(expiresInDays !== undefined && { expires_in_days: expiresInDays }) },
      }),
    revoke: async (keyId: string): Promise<void> => {
      await this.call("DELETE", `/v1/api-keys/${keyId}`);
    },
  };

  constructor(baseUrl: string, options: SynapseClientOptions = {}) {
    if (!options.apiKey && !options.accessToken) {
      throw new Error("apiKey or accessToken is required");
    }
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.headers = {
      Authorization: `Bearer ${options.apiKey ?? options.accessToken}`,
      ...(options.orgId && { "X-Org-Id": options.orgId }),
    };
    this.timeoutMs = options.timeoutMs ?? 30_000;
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  private async send(method: string, path: string, options: RequestOptions = {}): Promise<Response> {
    const url = new URL(`${this.baseUrl}${path}`);
    for (const [key, value] of Object.entries(options.params ?? {})) {
      if (value !== undefined) url.searchParams.set(key, String(value));
    }
    return this.fetchImpl(url.toString(), {
      method,
      headers: {
        ...this.headers,
        ...(options.body && { "Content-Type": "application/json" }),
        ...options.headers,
      },
      body: options.form ?? (options.body ? JSON.stringify(options.body) : undefined),
      signal: AbortSignal.timeout(this.timeoutMs),
    });
  }

  // Internal: returns parsed JSON, undefined for 204. Callers declare the
  // public type at each resource method.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private async call(method: string, path: string, options: RequestOptions = {}): Promise<any> {
    const response = await this.send(method, path, options);
    if (response.status === 204) return;
    const body = (await response.json()) as Json;
    if (!response.ok) {
      throw errorFor(response.status, body as unknown as Problem);
    }
    return body;
  }

  private async callPage(path: string, paging: Paging): Promise<Page> {
    const response = await this.send("GET", path, { params: { limit: paging.limit, offset: paging.offset } });
    const body = (await response.json()) as Json;
    if (!response.ok) throw errorFor(response.status, body as unknown as Problem);
    const items = body as unknown as Json[];
    return {
      items,
      total: Number(response.headers.get("X-Total-Count") ?? items.length),
      limit: paging.limit ?? 50,
      offset: paging.offset ?? 0,
    };
  }

  private async callBytes(path: string): Promise<ArrayBuffer> {
    const response = await this.send("GET", path);
    if (!response.ok) {
      throw errorFor(response.status, (await response.json()) as unknown as Problem);
    }
    return response.arrayBuffer();
  }
}
