import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import {
  BUILTIN_STEP_IDS,
  DEFAULT_TOUR,
  type TourConfig,
  type TourStepConfig,
} from "@/lib/tour-config";
import { anchorRules, buildTour, type BuildTourInput } from "./steps";

const OWNER_PERMISSIONS = [
  "org:read",
  "org:update",
  "org:delete",
  "member:read",
  "member:invite",
  "member:update",
  "member:remove",
  "role:manage",
  "billing:read",
  "billing:manage",
  "usage:read",
  "audit:read",
  "webhook:manage",
  "apikey:manage",
  "agents:read",
  "agents:manage",
];
const DEVELOPER_PERMISSIONS = [
  "org:read",
  "member:read",
  "project:read",
  "project:manage",
  "webhook:manage",
  "usage:read",
  "apikey:manage",
  "agents:read",
];
const MEMBER_PERMISSIONS = ["org:read", "member:read", "project:read"];

type Viewer = Omit<BuildTourInput, "tour">;

const viewer = (role: string, permissions: readonly string[], extra: Partial<Viewer> = {}): Viewer => ({
  roleKeys: [role],
  permissions: new Set(permissions),
  isPlatformAdmin: false,
  isDesktop: true,
  brandName: "Acme",
  ...extra,
});

const OWNER = viewer("owner", OWNER_PERMISSIONS);
const MEMBER = viewer("member", MEMBER_PERMISSIONS);
const DEVELOPER = viewer("developer", DEVELOPER_PERMISSIONS);
const phone = (v: Viewer): Viewer => ({ ...v, isDesktop: false });

const custom = (overrides: Partial<TourStepConfig> = {}): TourStepConfig => ({
  id: "acme-step",
  title: "Acme step",
  content: "Acme content.",
  anchor: null,
  side: null,
  after: null,
  roles: null,
  permissions: null,
  icon: "sparkles",
  link: null,
  ...overrides,
});

const tourOf = (overrides: Partial<TourConfig>): TourConfig => ({ ...DEFAULT_TOUR, ...overrides });

const steps = (v: Viewer, tour: TourConfig = DEFAULT_TOUR) => buildTour({ ...v, tour }).steps;
const titles = (v: Viewer, tour: TourConfig = DEFAULT_TOUR) => steps(v, tour).map((s) => s.title);

describe("buildTour with no deployment config (pins 0.3.1 behaviour)", () => {
  it("gives a desktop owner 10 steps", () => {
    expect(titles(OWNER)).toEqual([
      "Welcome to Acme",
      "Your organization",
      "Plan and status",
      "Usage this period",
      "Enabled features",
      "Members",
      "API keys",
      "Developer",
      "Billing",
      "That's it",
    ]);
  });

  it("gives a member 4 steps", () => {
    expect(titles(MEMBER)).toEqual([
      "Welcome to Acme",
      "Your organization",
      "Enabled features",
      "That's it",
    ]);
  });

  it("gives a mobile owner 5 steps with the last one centred", () => {
    const mobile = steps(phone(OWNER));
    expect(mobile.map((s) => s.title)).toEqual([
      "Welcome to Acme",
      "Plan and status",
      "Usage this period",
      "Enabled features",
      "That's it",
    ]);
    expect(mobile.at(-1)?.selector).toBeUndefined();
  });

  it("shows the Admin step to platform admins only", () => {
    expect(titles({ ...OWNER, isPlatformAdmin: true })).toContain("Admin");
    expect(titles(OWNER)).not.toContain("Admin");
  });
});

describe("anchorRules", () => {
  it("derives the nav permission from the route map", () => {
    expect(anchorRules("nav-members").permission).toBe("member:read");
    expect(anchorRules("nav-api-keys").permission).toBe("apikey:manage");
    expect(anchorRules("nav-webhooks").permission).toBe("webhook:manage");
    expect(anchorRules("nav-dashboard").permission).toBeUndefined();
    expect(anchorRules("nav-settings").permission).toBeUndefined();
    expect(anchorRules("plan").permission).toBeUndefined();
  });

  it("marks every anchor but the dashboard cards as living in the menu", () => {
    expect(anchorRules("plan").menu).toBe(false);
    expect(anchorRules("usage").menu).toBe(false);
    expect(anchorRules("features").menu).toBe(false);
    expect(anchorRules("org-switcher").menu).toBe(true);
    expect(anchorRules("nav-usage").menu).toBe(true);
    expect(anchorRules("take-the-tour").menu).toBe(true);
  });

  it("gates nav-admin to platform admins and picks a default side", () => {
    expect(anchorRules("nav-admin").platformAdminOnly).toBe(true);
    expect(anchorRules("nav-members").platformAdminOnly).toBe(false);
    expect(anchorRules("plan").side).toBe("bottom-left");
    expect(anchorRules("usage").side).toBe("bottom");
    expect(anchorRules("features").side).toBe("bottom");
    expect(anchorRules("take-the-tour").side).toBe("right-bottom");
    expect(anchorRules("nav-billing").side).toBe("right");
  });
});

describe("buildTour with deployment steps", () => {
  it("hides built-in steps and ignores nothing else", () => {
    const result = titles(OWNER, tourOf({ hide: ["nav-members", "plan"] }));
    expect(result).toHaveLength(8);
    expect(result).not.toContain("Members");
    expect(result).not.toContain("Plan and status");
  });

  it("places a step without `after` just before the last step, in declared order", () => {
    const tour = tourOf({
      steps: [custom({ id: "a", title: "First" }), custom({ id: "b", title: "Second" })],
    });
    expect(titles(OWNER, tour).slice(-3)).toEqual(["First", "Second", "That's it"]);
  });

  it("keeps `after` order when the viewer cannot see the anchor step", () => {
    // Owners never see the developer-only Agents step; the custom step still follows Members.
    const tour = tourOf({ steps: [custom({ title: "After agents", after: "nav-agents" })] });
    const result = titles(OWNER, tour);
    expect(result.slice(result.indexOf("Members"), result.indexOf("Members") + 3)).toEqual([
      "Members",
      "After agents",
      "API keys",
    ]);
  });

  it("drops a nav-anchored step the viewer lacks the permission for", () => {
    const tour = tourOf({ steps: [custom({ anchor: "nav-api-keys" })] });
    expect(titles(MEMBER, tour)).not.toContain("Acme step");
    const anchored = steps(OWNER, tour).find((s) => s.title === "Acme step");
    expect(anchored?.selector).toBe('[data-tour="nav-api-keys"]');
    expect(anchored?.side).toBe("right");
  });

  it("centres a menu-anchored step on a phone instead of dropping it", () => {
    const tour = tourOf({ steps: [custom({ anchor: "nav-api-keys", side: "left" })] });
    const mobile = steps(phone(OWNER), tour);
    const centred = mobile.find((s) => s.title === "Acme step");
    expect(centred).toBeDefined();
    expect(centred?.selector).toBeUndefined();
    expect(titles(phone(MEMBER), tour)).not.toContain("Acme step");
  });

  it("keeps a dashboard-card anchor on a phone with its default side", () => {
    const tour = tourOf({ steps: [custom({ anchor: "plan" })] });
    const step = steps(phone(OWNER), tour).find((s) => s.title === "Acme step");
    expect(step?.selector).toBe('[data-tour="plan"]');
    expect(step?.side).toBe("bottom-left");
  });

  it("requires a platform admin for nav-admin and still honours roles", () => {
    const tour = tourOf({ steps: [custom({ anchor: "nav-admin", roles: ["developer"] })] });
    expect(titles({ ...DEVELOPER }, tour)).not.toContain("Acme step");
    expect(titles({ ...OWNER, isPlatformAdmin: true }, tour)).not.toContain("Acme step");
    expect(titles({ ...DEVELOPER, isPlatformAdmin: true }, tour)).toContain("Acme step");
  });

  it("requires every listed permission", () => {
    const tour = tourOf({ steps: [custom({ permissions: ["apikey:manage", "billing:read"] })] });
    expect(titles(DEVELOPER, tour)).not.toContain("Acme step");
    expect(titles(OWNER, tour)).toContain("Acme step");
  });

  it("accepts any listed role", () => {
    const tour = tourOf({ steps: [custom({ roles: ["billing", "developer"] })] });
    expect(titles(DEVELOPER, tour)).toContain("Acme step");
    expect(titles(MEMBER, tour)).not.toContain("Acme step");
  });

  it("yields zero steps when every built-in is hidden", () => {
    expect(steps(OWNER, tourOf({ hide: [...BUILTIN_STEP_IDS] }))).toEqual([]);
  });

  it("renders a link as a new-tab anchor inside the content", () => {
    const tour = tourOf({
      steps: [custom({ link: { label: "Open Acme", href: "https://example.com/acme" } })],
    });
    const step = steps(OWNER, tour).find((s) => s.title === "Acme step");
    const html = renderToStaticMarkup(<>{step?.content}</>);
    expect(html).toContain("Acme content.");
    expect(html).toMatch(/<a [^>]*href="https:\/\/example.com\/acme"/);
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
    expect(html).toContain("Open Acme");
  });

  it("places `after: done` after the last built-in step", () => {
    const tour = tourOf({ steps: [custom({ title: "Epilogue", after: "done" })] });
    expect(titles(OWNER, tour).slice(-2)).toEqual(["That's it", "Epilogue"]);
  });

  it("keeps default-group steps at the end when `done` is hidden", () => {
    const tour = tourOf({ hide: ["done"], steps: [custom({ title: "Closing" })] });
    expect(titles(OWNER, tour).slice(-2)).toEqual(["Billing", "Closing"]);
  });

  it("keeps a step placed after a hidden built-in at that position (insert runs before hide)", () => {
    const tour = tourOf({
      hide: ["nav-api-keys"],
      steps: [custom({ title: "Where keys were", after: "nav-api-keys" })],
    });
    const result = titles(OWNER, tour);
    expect(result).not.toContain("API keys");
    expect(result.slice(result.indexOf("Members"), result.indexOf("Members") + 3)).toEqual([
      "Members",
      "Where keys were",
      "Developer",
    ]);
  });

  it("keeps declared order within each `after` group, whatever the group order", () => {
    const tour = tourOf({
      steps: [
        custom({ id: "b1", title: "B1", after: "nav-billing" }),
        custom({ id: "w1", title: "W1", after: "welcome" }),
        custom({ id: "b2", title: "B2", after: "nav-billing" }),
        custom({ id: "w2", title: "W2", after: "welcome" }),
      ],
    });
    const result = titles(OWNER, tour);
    expect(result.slice(0, 3)).toEqual(["Welcome to Acme", "W1", "W2"]);
    expect(result.slice(result.indexOf("Billing"), result.indexOf("Billing") + 3)).toEqual([
      "Billing",
      "B1",
      "B2",
    ]);
  });

  it("centres the org switcher and dashboard nav anchors on a phone", () => {
    const tour = tourOf({
      steps: [
        custom({ id: "a", title: "Switcher", anchor: "org-switcher" }),
        custom({ id: "b", title: "Home", anchor: "nav-dashboard" }),
      ],
    });
    const mobile = steps(phone(MEMBER), tour).filter((s) => ["Switcher", "Home"].includes(s.title));
    expect(mobile.map((s) => [s.title, s.selector])).toEqual([
      ["Switcher", undefined],
      ["Home", undefined],
    ]);
  });

  it("matches the e2e fixture kit for a developer on desktop and phone", () => {
    const kit = tourOf({
      hide: ["nav-agents"],
      steps: [
        custom({
          id: "e2e-api-key",
          title: "Enroll your API key",
          anchor: "nav-api-keys",
          after: "nav-api-keys",
          icon: "key",
          roles: ["developer"],
          link: { label: "Open Acme", href: "https://example.com/acme" },
        }),
        custom({ id: "e2e-finish", title: "Before you go", roles: ["developer"] }),
      ],
    });
    expect(titles(DEVELOPER, kit).slice(1)).toEqual([
      "Your organization",
      "Usage this period",
      "Enabled features",
      "API keys",
      "Enroll your API key",
      "Developer",
      "Webhooks",
      "Before you go",
      "That's it",
    ]);
    expect(titles(phone(DEVELOPER), kit).slice(1)).toEqual([
      "Usage this period",
      "Enabled features",
      "Enroll your API key",
      "Before you go",
      "That's it",
    ]);
    expect(titles(OWNER, kit)).toHaveLength(10);
    expect(titles(OWNER, kit)).not.toContain("Enroll your API key");
  });
});
