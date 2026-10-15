"use client";

/* The console welcome tour: one ordered step list, filtered per viewer.
 *
 * Every step lives on /dashboard (no `nextRoute`): nav links are visible
 * targets, and role-gated pages are never navigated into. Anchors are
 * `data-tour="…"` attributes in app-shell.tsx and dashboard/page.tsx — forks
 * add steps here or retarget those attributes. */

import type { ReactNode } from "react";
import type { Step, Tour } from "nextstepjs";
import {
  BarChart3,
  Bot,
  Building2,
  Code2,
  Compass,
  CreditCard,
  Gauge,
  KeyRound,
  Receipt,
  ShieldCheck,
  Sparkles,
  ToggleRight,
  Users,
  Webhook,
} from "lucide-react";
import { hasPermission, ROUTE_PERMISSIONS } from "@/lib/permissions";

export const TOUR_NAME = "console-welcome";
/** Bump to re-offer the tour after a redesign (auto-start compares versions). */
export const TOUR_VERSION = 1;

const POINTER_PADDING = 6;
const POINTER_RADIUS = 8;

type Side = NonNullable<Step["side"]>;

interface StepDef {
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
}

export interface BuildTourInput {
  roleKeys: readonly string[];
  /** The active org's permission keys (`orgs[].permission_keys`). */
  permissions: ReadonlySet<string>;
  isPlatformAdmin: boolean;
  isDesktop: boolean;
  brandName: string;
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

function isVisible(def: StepDef, input: BuildTourInput, roles: ReadonlySet<string>): boolean {
  if (def.desktopOnly && !input.isDesktop) return false;
  if (def.platformAdminOnly) return input.isPlatformAdmin;
  if (!hasPermission(input.permissions, input.isPlatformAdmin, def.permission)) return false;
  return def.roles === undefined || def.roles.some((role) => roles.has(role));
}

/** Pure: the tour for one viewer (role and permission keys of the active org, viewport, brand). */
export function buildTour(input: BuildTourInput): Tour {
  // An empty role list is displayed as "member" by the shell; treat it the same.
  const roles = new Set(input.roleKeys.length > 0 ? input.roleKeys : ["member"]);
  const steps: Step[] = stepDefs(input.brandName, input.isDesktop)
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
