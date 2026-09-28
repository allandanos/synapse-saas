import { describe, expect, it } from "vitest";
import {
  SynapseClient,
  SynapseAuthError,
  SynapseFeatureGatedError,
  SynapseLimitError,
  SynapseNotFoundError,
} from "../src/index.js";

type Recorded = { method: string; url: string; body?: string; auth: string | null; org: string | null };

function fakeFetch(responses: Array<{ status: number; body: unknown }>) {
  const requests: Recorded[] = [];
  let call = 0;
  const impl: typeof fetch = async (input, init) => {
    const url = String(input);
    requests.push({
      method: init?.method ?? "GET",
      url,
      body: typeof init?.body === "string" ? init.body : undefined,
      auth: (init?.headers as Record<string, string>)?.Authorization ?? null,
      org: (init?.headers as Record<string, string>)?.["X-Org-Id"] ?? null,
    });
    const preset = responses[Math.min(call, responses.length - 1)];
    call += 1;
    // 204 must carry an empty body — Response(null) makes .json() throw
    if (preset.status === 204) return new Response(null, { status: 204 });
    return new Response(JSON.stringify(preset.body), { status: preset.status });
  };
  return { impl, requests };
}

function client(fetchImpl: typeof fetch, orgId?: string) {
  return new SynapseClient("http://test", { apiKey: "sk_test", orgId, fetchImpl });
}

describe("requests", () => {
  it("sends auth + org headers", async () => {
    const { impl, requests } = fakeFetch([{ status: 200, body: { id: "u1" } }]);
    const c = client(impl, "11111111-1111-1111-1111-111111111111");
    await c.auth.me();
    expect(requests[0].auth).toBe("Bearer sk_test");
    expect(requests[0].org).toBe("11111111-1111-1111-1111-111111111111");
  });

  it("shapes consume payloads", async () => {
    const { impl, requests } = fakeFetch([{ status: 200, body: { total: 5 } }]);
    const c = client(impl);
    const result = (await c.usage.consume("api_requests", 5)) as { total: number };
    expect(result.total).toBe(5);
    expect(JSON.parse(requests[0].body!)).toEqual({
      events: [{ metric: "api_requests", quantity: 5 }],
    });
  });

  it("query params land in the URL", async () => {
    const { impl, requests } = fakeFetch([{ status: 200, body: {} }]);
    const c = client(impl);
    await c.usage.check("api_requests", 2);
    expect(requests[0].url).toContain("metric=api_requests");
    expect(requests[0].url).toContain("quantity=2");
  });

  it("204 returns undefined", async () => {
    const { impl } = fakeFetch([{ status: 204, body: null }]);
    const c = client(impl);
    expect(await c.apiKeys.revoke("k1")).toBeUndefined();
  });
});

describe("errors", () => {
  it("402 maps to SynapseLimitError with metric + limit", async () => {
    const { impl } = fakeFetch([
      { status: 402, body: { title: "usage limit exceeded", metric: "api_requests", limit: 100 } },
    ]);
    const c = client(impl);
    await expect(c.usage.consume("api_requests", 500)).rejects.toMatchObject({
      name: "SynapseLimitError",
      metric: "api_requests",
      limit: 100,
    });
  });

  it("403 feature gates carry available_in", async () => {
    const { impl } = fakeFetch([
      {
        status: 403,
        body: { title: "feature not entitled", feature: "advanced_reports", available_in: ["pro"] },
      },
    ]);
    const c = client(impl);
    try {
      await c.subscription.change("pro");
      expect.unreachable();
    } catch (err) {
      expect(err).toBeInstanceOf(SynapseFeatureGatedError);
      expect((err as SynapseFeatureGatedError).availableIn).toEqual(["pro"]);
    }
  });

  it("404 and 401 map to their types", async () => {
    const nf = fakeFetch([{ status: 404, body: { title: "not found" } }]);
    await expect(client(nf.impl).orgs.current()).rejects.toBeInstanceOf(SynapseNotFoundError);

    const au = fakeFetch([{ status: 401, body: { title: "unauthorized" } }]);
    await expect(client(au.impl).auth.me()).rejects.toBeInstanceOf(SynapseAuthError);
  });
});

describe("constructor", () => {
  it("requires credentials", () => {
    expect(() => new SynapseClient("http://test", {})).toThrow(/apiKey or accessToken/);
  });

  it("access token mode", async () => {
    const { impl, requests } = fakeFetch([{ status: 200, body: {} }]);
    const c = new SynapseClient("http://test", { accessToken: "jwt", fetchImpl: impl });
    await c.auth.me();
    expect(requests[0].auth).toBe("Bearer jwt");
  });
});

function fakeFetchWithHeaders(status: number, body: BodyInit | null, headers: Record<string, string>) {
  const requests: Array<{ method: string; url: string; body: unknown; contentType: string | null }> = [];
  const impl: typeof fetch = async (input, init) => {
    requests.push({
      method: init?.method ?? "GET",
      url: String(input),
      body: init?.body,
      contentType: (init?.headers as Record<string, string>)?.["Content-Type"] ?? null,
    });
    return new Response(body, { status, headers });
  };
  return { impl, requests };
}

describe("full contract surface", () => {
  it("pages read X-Total-Count and pass paging params", async () => {
    const { impl, requests } = fakeFetchWithHeaders(200, JSON.stringify([{ id: "a" }, { id: "b" }]), {
      "X-Total-Count": "7",
    });
    const page = await client(impl).invoices.listPage({ limit: 2, offset: 4 });
    expect(page).toEqual({ items: [{ id: "a" }, { id: "b" }], total: 7, limit: 2, offset: 4 });
    expect(requests[0].url).toBe("http://test/v1/billing/invoices?limit=2&offset=4");
  });

  it("bytes routes return the raw body", async () => {
    const { impl } = fakeFetchWithHeaders(200, new Uint8Array([37, 80, 68, 70]), { "Content-Type": "application/pdf" });
    const pdf = await client(impl).invoices.pdf("inv1");
    expect(new Uint8Array(pdf)).toEqual(new Uint8Array([37, 80, 68, 70]));
  });

  it("bytes route errors still map to typed errors", async () => {
    const { impl } = fakeFetchWithHeaders(404, JSON.stringify({ title: "not found" }), {});
    await expect(client(impl).files.download("nope")).rejects.toBeInstanceOf(SynapseNotFoundError);
  });

  it("uploads as multipart without a JSON content type", async () => {
    const { impl, requests } = fakeFetchWithHeaders(201, JSON.stringify({ id: "f1" }), {});
    await client(impl).files.upload("a.txt", new Uint8Array([104, 105]), "text/plain");
    expect(requests[0].body).toBeInstanceOf(FormData);
    expect(requests[0].contentType).toBeNull();
    expect((requests[0].body as FormData).get("file")).toBeInstanceOf(Blob);
  });

  it("shapes admin, auth, flags, roles and usage.record payloads", async () => {
    const { impl, requests } = fakeFetchWithHeaders(200, JSON.stringify({}), {});
    const c = client(impl);
    await c.auth.login("a@b.c", "pw");
    expect(JSON.parse(requests[0].body as string)).toEqual({ email: "a@b.c", password: "pw" });
    await c.featureFlags.setOverride("k", { enabled: true, organizationId: "o1" });
    expect(JSON.parse(requests[1].body as string)).toEqual({ enabled: true, organization_id: "o1" });
    await c.roles.update("r1", { permissions: ["org:read"] });
    expect(JSON.parse(requests[2].body as string)).toEqual({ permissions: ["org:read"] });
    await c.usage.record([{ metric: "api_requests", quantity: 2, idempotencyKey: "k1" }]);
    expect(requests[3].url).toBe("http://test/v1/usage/events");
    expect(JSON.parse(requests[3].body as string).events[0]).toEqual({
      metric: "api_requests",
      quantity: 2,
      idempotency_key: "k1",
    });
    await c.webhooks.listDeliveries({ endpointId: "e1", limit: 10 });
    expect(requests[4].url).toBe("http://test/v1/webhooks/deliveries?limit=10&endpoint_id=e1");
    await c.admin.suspendOrg("org1");
    expect(requests[5]).toMatchObject({ method: "POST", url: "http://test/v1/orgs/org1/suspend" });
  });
});
