import { describe, expect, it } from "vitest";
import { BUILTIN_STEP_IDS, DEFAULT_TOUR, parseTour } from "./tour-config";

const step = (overrides: Record<string, unknown> = {}): Record<string, unknown> => ({
  id: "acme-key",
  title: "Enroll your key",
  content: "Paste it into the vault.",
  ...overrides,
});

describe("parseTour", () => {
  it("returns the default for an absent or non-object tour (older API)", () => {
    expect(parseTour(undefined)).toEqual(DEFAULT_TOUR);
    expect(parseTour(null)).toEqual(DEFAULT_TOUR);
    expect(parseTour("tour")).toEqual(DEFAULT_TOUR);
    expect(parseTour([])).toEqual(DEFAULT_TOUR);
    expect(DEFAULT_TOUR).toEqual({ enabled: true, hide: [], steps: [] });
  });

  it("only an explicit false disables the tour", () => {
    expect(parseTour({ enabled: false }).enabled).toBe(false);
    expect(parseTour({ enabled: "no" }).enabled).toBe(true);
    expect(parseTour({}).enabled).toBe(true);
  });

  it("keeps a fully specified step", () => {
    const tour = parseTour({
      steps: [
        step({
          anchor: "nav-api-keys",
          side: "left",
          after: "nav-api-keys",
          roles: ["developer"],
          permissions: ["apikey:manage"],
          icon: "key",
          link: { label: "Open Acme", href: "https://example.com/acme" },
        }),
      ],
    });
    expect(tour.steps).toEqual([
      {
        id: "acme-key",
        title: "Enroll your key",
        content: "Paste it into the vault.",
        anchor: "nav-api-keys",
        side: "left",
        after: "nav-api-keys",
        roles: ["developer"],
        permissions: ["apikey:manage"],
        icon: "key",
        link: { label: "Open Acme", href: "https://example.com/acme" },
      },
    ]);
  });

  it("fills optional fields with null and the sparkles icon", () => {
    expect(parseTour({ steps: [step()] }).steps[0]).toEqual({
      id: "acme-key",
      title: "Enroll your key",
      content: "Paste it into the vault.",
      anchor: null,
      side: null,
      after: null,
      roles: null,
      permissions: null,
      icon: "sparkles",
      link: null,
    });
  });

  it("drops steps with an invalid id, title, content or anchor", () => {
    const tour = parseTour({
      steps: [
        step({ id: "Bad Id" }),
        step({ id: "9lives" }),
        step({ id: "no-title", title: "" }),
        step({ id: "long-title", title: "x".repeat(81) }),
        step({ id: "no-content", content: "" }),
        step({ id: "long-content", content: "x".repeat(401) }),
        step({ id: "bad-anchor", anchor: "nav-nowhere" }),
        "not a step",
        step({ id: "kept" }),
      ],
    });
    expect(tour.steps.map((s) => s.id)).toEqual(["kept"]);
  });

  it("drops a step that reuses a built-in id", () => {
    expect(parseTour({ steps: [step({ id: "welcome" })] }).steps).toEqual([]);
  });

  it("falls back for an unknown icon, side or after", () => {
    const [parsed] = parseTour({
      steps: [step({ icon: "unicorn", side: "middle", after: "nowhere" })],
    }).steps;
    expect(parsed.icon).toBe("sparkles");
    expect(parsed.side).toBeNull();
    expect(parsed.after).toBeNull();
  });

  it("drops a link that is not http(s) or has a bad label", () => {
    const links = [
      { label: "Run", href: "javascript:alert(1)" },
      { label: "Relative", href: "/accreditation" },
      { label: "Ftp", href: "ftp://example.com" },
      { label: "", href: "https://example.com" },
      { label: "x".repeat(41), href: "https://example.com" },
      "https://example.com",
    ];
    const tour = parseTour({ steps: links.map((link, i) => step({ id: `s${i}`, link })) });
    expect(tour.steps.map((s) => s.link)).toEqual(links.map(() => null));
  });

  it("drops a step whose roles or permissions are present but malformed (fails closed)", () => {
    const malformed = [
      { roles: "owner" },
      { roles: [] },
      { roles: ["owner", ""] },
      { roles: ["Owner"] },
      { roles: Array.from({ length: 11 }, (_, i) => `role_${i}`) },
      { permissions: [1] },
      { permissions: ["apikey-manage"] },
      { permissions: {} },
    ];
    const tour = parseTour({ steps: malformed.map((gate, i) => step({ id: `s${i}`, ...gate })) });
    expect(tour.steps).toEqual([]);
  });

  it("treats absent or null roles and permissions as no gate", () => {
    const tour = parseTour({
      steps: [step({ id: "a" }), step({ id: "b", roles: null, permissions: null })],
    });
    expect(tour.steps.map((s) => [s.id, s.roles, s.permissions])).toEqual([
      ["a", null, null],
      ["b", null, null],
    ]);
  });

  it("accepts custom role keys and well-formed permission keys", () => {
    const [parsed] = parseTour({
      steps: [step({ roles: ["owner", "eis_maker"], permissions: ["apikey:manage"] })],
    }).steps;
    expect(parsed.roles).toEqual(["owner", "eis_maker"]);
    expect(parsed.permissions).toEqual(["apikey:manage"]);
  });

  it("rejects control characters like the API's single-line rule", () => {
    const tour = parseTour({
      steps: [
        step({ id: "newline", content: "Line one\nline two" }),
        step({ id: "tab-title", title: "Tab\there" }),
        step({ id: "del", content: "Delete\u007f" }),
        step({ id: "bad-label", link: { label: "Open\nAcme", href: "https://example.com" } }),
      ],
    });
    expect(tour.steps.map((s) => [s.id, s.link])).toEqual([["bad-label", null]]);
  });

  it("keeps the first of duplicate ids and caps the list at 20", () => {
    const many = Array.from({ length: 25 }, (_, i) => step({ id: `s${i}` }));
    const tour = parseTour({ steps: [step({ id: "s0", title: "First" }), ...many] });
    expect(tour.steps).toHaveLength(20);
    expect(tour.steps[0].title).toBe("First");
    expect(new Set(tour.steps.map((s) => s.id)).size).toBe(20);
  });

  it("keeps only built-in ids in hide, without duplicates", () => {
    expect(parseTour({ hide: ["nav-agents", "nope", 3, "nav-agents", "plan"] }).hide).toEqual([
      "nav-agents",
      "plan",
    ]);
    expect(parseTour({ hide: "nav-agents" }).hide).toEqual([]);
  });

  it("never throws on hostile input", () => {
    const hostile = { steps: [null, 1, [], { id: {} }], hide: [null], enabled: {} };
    expect(() => parseTour(hostile)).not.toThrow();
    expect(parseTour({ steps: "nope" }).steps).toEqual([]);
  });

  it("ignores __proto__ and constructor keys at every level", () => {
    const raw: unknown = JSON.parse(
      JSON.stringify({
        __proto__placeholder: true,
        enabled: true,
        hide: ["constructor", "__proto__", "plan"],
        steps: [
          step({ id: "constructor", roles: ["owner"], link: { constructor: 1, label: "Go", href: "https://example.com" } }),
          { __proto__placeholder: { steps: [] }, id: "x", title: "t", content: "c" },
        ],
      }).replace(/__proto__placeholder/g, "__proto__"),
    );
    const parse = () => parseTour(raw);
    expect(parse).not.toThrow();
    const tour = parse();
    expect(tour.enabled).toBe(true);
    expect(tour.hide).toEqual(["plan"]);
    expect(tour.steps.map((s) => s.id)).toEqual(["constructor", "x"]);
    expect(tour.steps[0].link).toEqual({ label: "Go", href: "https://example.com" });
    expect(({} as Record<string, unknown>).steps).toBeUndefined(); // no prototype pollution
    expect(parseTour(JSON.parse('{"__proto__": {"enabled": false}, "constructor": {}}'))).toEqual(
      DEFAULT_TOUR,
    );
  });

  it("bounds the work on huge step and hide arrays", () => {
    const steps = Array.from({ length: 50_000 }, (_, i) => step({ id: `s${i}` }));
    const tour = parseTour({ steps });
    expect(tour.steps.map((s) => s.id)).toEqual(Array.from({ length: 20 }, (_, i) => `s${i}`));

    const hide = Array.from({ length: 50_000 }, (_, i) => BUILTIN_STEP_IDS[i % BUILTIN_STEP_IDS.length]);
    expect(parseTour({ hide }).hide).toEqual([...BUILTIN_STEP_IDS]);
  });
});
