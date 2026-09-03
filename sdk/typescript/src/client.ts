import { errorFor, type Problem } from "./errors.js";

type Json = Record<string, unknown>;

interface RequestOptions {
  method?: string;
  body?: Json;
  params?: Record<string, string | number | undefined>;
  headers?: Record<string, string>;
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
  };

  readonly orgs = {
    list: (): Promise<Json> => this.call("GET", "/v1/orgs"),
    create: (name: string, slug?: string): Promise<Json> =>
      this.call("POST", "/v1/orgs", { body: { name, slug } }),
    current: (): Promise<Json> => this.call("GET", "/v1/orgs/current"),
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
  };

  readonly usage = {
    summary: (period?: string): Promise<Json> =>
      this.call("GET", "/v1/usage/summary", { params: { period } }),
    check: (metric: string, quantity = 1): Promise<Json> =>
      this.call("GET", "/v1/usage/check", { params: { metric, quantity } }),
    consume: (metric: string, quantity = 1): Promise<Json> =>
      this.call("POST", "/v1/usage/consume", {
        body: { events: [{ metric, quantity }] },
      }),
  };

  readonly entitlements = {
    effective: (): Promise<Json> => this.call("GET", "/v1/entitlements"),
    grant: (
      featureKey: string,
      source: string,
      opts: { durationDays?: number; limitValue?: number } = {},
    ): Promise<Json> =>
      this.call("POST", "/v1/entitlements/grants", {
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

  // Internal: returns parsed JSON, undefined for 204. Callers declare the
  // public type at each resource method.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private async call(method: string, path: string, options: RequestOptions = {}): Promise<any> {
    const url = new URL(`${this.baseUrl}${path}`);
    for (const [key, value] of Object.entries(options.params ?? {})) {
      if (value !== undefined) url.searchParams.set(key, String(value));
    }

    const response = await this.fetchImpl(url.toString(), {
      method,
      headers: {
        ...this.headers,
        ...(options.body && { "Content-Type": "application/json" }),
        ...options.headers,
      },
      body: options.body ? JSON.stringify(options.body) : undefined,
      signal: AbortSignal.timeout(this.timeoutMs),
    });

    if (response.status === 204) return;
    const body = (await response.json()) as Json;
    if (!response.ok) {
      throw errorFor(response.status, body as unknown as Problem);
    }
    return body;
  }
}
