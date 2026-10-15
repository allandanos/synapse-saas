"use client";

/* The console welcome tour: one ordered step list, filtered per viewer.
 *
 * Every step lives on /dashboard (no `nextRoute`): nav links are visible
 * targets, and role-gated pages are never navigated into. Anchors are
 * `data-tour="…"` attributes in app-shell.tsx and dashboard/page.tsx.
 *
 * Deployments add, hide or disable steps from `branding.yaml` (`tour:`, parsed
 * by lib/tour-config.ts) and `composeSteps` merges them in here; forks add
 * built-in steps or new anchors in this file. */

import type { ReactNode } from "react";
import type { Step, Tour } from "nextstepjs";
import {
  BarChart3,
  BookOpen,
  Bot,
  Building2,
  ClipboardCheck,
  Code2,
  Compass,
  CreditCard,
  FileText,
  Gauge,
  KeyRound,
  Lightbulb,
  Link as LinkIcon,
  Mail,
  Plug,
  Receipt,
  Rocket,
  ShieldCheck,
  Sparkles,
  ToggleRight,
  Users,
  Webhook,
} from "lucide-react";
import { hasPermission, ROUTE_PERMISSIONS } from "@/lib/permissions";
import type { TourAnchor, TourConfig, TourIconName, TourStepConfig } from "@/lib/tour-config";
import { StepLink } from "./tour-card";

export const TOUR_NAME = "console-welcome";
/** Bump to re-offer the tour after a redesign (auto-start compares versions). */
export const TOUR_VERSION = 1;

const POINTER_PADDING = 6;
const POINTER_RADIUS = 8;

type Side = NonNullable<Step["side"]>;

export interface StepDef {
  id: string;
  title: string;
  content: ReactNode;
  selector?: string;
  side?: Side;
  icon: ReactNode;
  /** Shown when the viewer holds any of these roles; undefined = everyone. */
  roles?: readonly string[];
  /** Target lives inside #app-menu, which is hidden below `md`. */
  desktopOnly?: boolean;
  platformAdminOnly?: boolean;
  /** AND-guard on top of `roles`: never anchor to a nav link the shell hides. */
  permission?: string;
  /** Extra all-of permission guard (deployment steps' `permissions`). */
  permissions?: readonly string[];
}

export interface BuildTourInput {
  roleKeys: readonly string[];
  /** The active org's permission keys (`orgs[].permission_keys`). */
  permissions: ReadonlySet<string>;
  isPlatformAdmin: boolean;
  isDesktop: boolean;
  brandName: string;
  /** Deployment additions from `branding.yaml` (`DEFAULT_TOUR` when none). */
  tour: TourConfig;
}

const icon = (Icon: typeof Sparkles) => <Icon className="h-4 w-4" aria-hidden />;
const anchor = (id: string) => `[data-tour="${id}"]`;

function stepDefs(brandName: string, isDesktop: boolean): readonly StepDef[] {
  return [
    {
      id: "welcome",
      title: `Welcome to ${brandName}`,
      content: "A two-minute look at where things live. Use the buttons or ← →; Esc skips.",
      icon: icon(Sparkles),
    },
    {
      id: "org-switcher",
      title: "Your organization",
      content:
        "Everything here is scoped to the selected organization; switch or create one from this list.",
      selector: anchor("org-switcher"),
      side: "right",
      icon: icon(Building2),
      desktopOnly: true,
    },
    {
      id: "plan",
      title: "Plan and status",
      content: "The current plan and subscription state. New organizations start on Free.",
      selector: anchor("plan"),
      side: "bottom-left",
      icon: icon(Receipt),
      roles: ["owner", "admin", "billing"],
    },
    {
      id: "usage",
      title: "Usage this period",
      content:
        "Meters fill as the organization consumes seats and metered resources; limits come from the plan.",
      selector: anchor("usage"),
      side: "bottom",
      icon: icon(Gauge),
      roles: ["owner", "admin", "billing", "developer"],
    },
    {
      id: "features",
      title: "Enabled features",
      content: "What the plan or a grant unlocks. Gated screens check these, never the plan name.",
      selector: anchor("features"),
      side: "bottom",
      icon: icon(ToggleRight),
    },
    navStep("members", "Members", "Invite teammates and set their roles.", Users, ["owner", "admin"]),
    navStep("agents", "Agents", "Register and govern the agents your product runs.", Bot, ["developer"]),
    navStep(
      "api-keys",
      "API keys",
      "Scoped keys for server-to-server calls; the secret is shown once.",
      KeyRound,
      ["owner", "admin", "developer"],
    ),
    navStep(
      "developer",
      "Developer",
      "Probe endpoints, check feature flags, copy SDK snippets.",
      Code2,
      ["owner", "admin", "developer"],
    ),
    navStep("webhooks", "Webhooks", "Subscribe to events; deliveries are signed and retried.", Webhook, [
      "developer",
    ]),
    navStep(
      "billing",
      "Billing",
      "Change plan, payment method, invoices and the billing contact.",
      CreditCard,
      ["owner", "admin", "billing"],
    ),
    navStep("usage", "Usage", "Per-metric history for the period.", BarChart3, ["billing"]),
    {
      ...navStep(
        "admin",
        "Admin",
        "Platform operator surface: every organization, grants and payments.",
        ShieldCheck,
      ),
      platformAdminOnly: true,
    },
    {
      id: "done",
      title: "That's it",
      content: "Replay this tour any time from here.",
      // The footer button is inside the collapsed mobile menu: centre the card there.
      selector: isDesktop ? anchor("take-the-tour") : undefined,
      side: "right-bottom",
      icon: icon(Compass),
    },
  ];
}

/** Built-in step ids in tour order; lib/tour-config.ts BUILTIN_STEP_IDS mirrors it (anchors.test.ts). */
export function builtinStepOrder(): readonly string[] {
  return stepDefs("", true).map((def) => def.id);
}

function navStep(
  id: string,
  title: string,
  content: string,
  Icon: typeof Sparkles,
  roles?: readonly string[],
): StepDef {
  return {
    id: `nav-${id}`,
    title,
    content,
    selector: anchor(`nav-${id}`),
    side: "right",
    icon: icon(Icon),
    roles,
    // Nav ids equal the route segments; the shell hides links by the same map.
    permission: ROUTE_PERMISSIONS[`/dashboard/${id}`],
    desktopOnly: true,
  };
}

/** What a deployment step inherits from its anchor, derived like `navStep()`. */
export interface AnchorRules {
  /** The anchor lives in #app-menu (collapsed below `md`): centre the card on phones. */
  menu: boolean;
  /** The permission the shell needs to show the anchor's nav link. */
  permission: string | undefined;
  platformAdminOnly: boolean;
  side: Side;
}

const PAGE_ANCHORS: ReadonlySet<TourAnchor> = new Set<TourAnchor>(["plan", "usage", "features"]);
const DEFAULT_SIDES: Partial<Record<TourAnchor, Side>> = {
  plan: "bottom-left",
  usage: "bottom",
  features: "bottom",
  "take-the-tour": "right-bottom",
};

export function anchorRules(target: TourAnchor): AnchorRules {
  return {
    menu: !PAGE_ANCHORS.has(target),
    permission: target.startsWith("nav-")
      ? ROUTE_PERMISSIONS[`/dashboard/${target.slice("nav-".length)}`]
      : undefined,
    platformAdminOnly: target === "nav-admin",
    side: DEFAULT_SIDES[target] ?? "right",
  };
}

const ICONS: Readonly<Record<TourIconName, typeof Sparkles>> = {
  sparkles: Sparkles,
  compass: Compass,
  building: Building2,
  receipt: Receipt,
  gauge: Gauge,
  toggle: ToggleRight,
  users: Users,
  bot: Bot,
  key: KeyRound,
  code: Code2,
  webhook: Webhook,
  "credit-card": CreditCard,
  chart: BarChart3,
  shield: ShieldCheck,
  rocket: Rocket,
  link: LinkIcon,
  mail: Mail,
  file: FileText,
  clipboard: ClipboardCheck,
  plug: Plug,
  book: BookOpen,
  lightbulb: Lightbulb,
};

function customContent(cfg: TourStepConfig): ReactNode {
  if (!cfg.link) return cfg.content;
  return (
    <>
      <span className="block">{cfg.content}</span>
      <StepLink href={cfg.link.href} label={cfg.link.label} />
    </>
  );
}

/** Phones collapse #app-menu: a menu anchor gets a centred card, like `done`. */
function customSelector(target: TourAnchor | null, isDesktop: boolean): string | undefined {
  if (target === null) return undefined;
  return anchorRules(target).menu && !isDesktop ? undefined : anchor(target);
}

function customStep(cfg: TourStepConfig, isDesktop: boolean): StepDef {
  const rules = cfg.anchor === null ? null : anchorRules(cfg.anchor);
  return {
    id: cfg.id,
    title: cfg.title,
    content: customContent(cfg),
    selector: customSelector(cfg.anchor, isDesktop),
    side: cfg.side ?? rules?.side,
    icon: icon(ICONS[cfg.icon]),
    roles: cfg.roles ?? undefined,
    permission: rules?.permission,
    permissions: cfg.permissions ?? undefined,
    platformAdminOnly: rules?.platformAdminOnly,
  };
}

const BEFORE_DONE = "__before_done__";

/**
 * Pure: the built-in steps with a deployment's steps inserted (grouped by
 * `after`, declared order kept; no `after` = just before `done`), then the
 * `hide` ids dropped. Runs before the viewer filters, so relative order
 * survives role filtering and hiding never invalidates a placement.
 */
export function composeSteps(
  builtins: readonly StepDef[],
  tour: TourConfig,
  isDesktop: boolean,
): readonly StepDef[] {
  const groups = tour.steps.reduce<Readonly<Record<string, readonly StepDef[]>>>((acc, cfg) => {
    const key = cfg.after ?? BEFORE_DONE;
    return { ...acc, [key]: [...(acc[key] ?? []), customStep(cfg, isDesktop)] };
  }, {});
  const hidden = new Set<string>(tour.hide);
  return builtins
    .flatMap((def) =>
      def.id === "done"
        ? [...(groups[BEFORE_DONE] ?? []), def, ...(groups[def.id] ?? [])]
        : [def, ...(groups[def.id] ?? [])],
    )
    .filter((def) => !hidden.has(def.id));
}

function isVisible(def: StepDef, input: BuildTourInput, roles: ReadonlySet<string>): boolean {
  if (def.desktopOnly && !input.isDesktop) return false;
  if (def.platformAdminOnly && !input.isPlatformAdmin) return false;
  const required = [def.permission, ...(def.permissions ?? [])];
  if (!required.every((p) => hasPermission(input.permissions, input.isPlatformAdmin, p))) {
    return false;
  }
  return def.roles === undefined || def.roles.some((role) => roles.has(role));
}

/** Pure: the tour for one viewer (role and permission keys of the active org, viewport, brand, deployment steps). */
export function buildTour(input: BuildTourInput): Tour {
  // An empty role list is displayed as "member" by the shell; treat it the same.
  const roles = new Set(input.roleKeys.length > 0 ? input.roleKeys : ["member"]);
  const steps: Step[] = composeSteps(
    stepDefs(input.brandName, input.isDesktop),
    input.tour,
    input.isDesktop,
  )
    .filter((def) => isVisible(def, input, roles))
    .map(({ title, content, selector, side, icon: stepIcon }) => ({
      title,
      content,
      selector,
      side,
      icon: stepIcon,
      pointerPadding: POINTER_PADDING,
      pointerRadius: POINTER_RADIUS,
    }));
  return { tour: TOUR_NAME, steps };
}
