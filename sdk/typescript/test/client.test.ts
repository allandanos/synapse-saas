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
