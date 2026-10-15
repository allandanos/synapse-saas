/* Deployment tour steps as served on `GET /v1/branding` (`tour`).
 *
 * Isomorphic and plain data: the server parses branding and hands it to the
 * client provider as a prop, so nothing here may hold JSX or functions, and
 * this module must never import the tour components. The enums mirror
 * `src/synapse_saas/branding/models.py` (BuiltinStepId, TourAnchor, TourSide,
 * TourIcon); the built-in ids are the steps in components/tour/steps.tsx and
 * the anchors are its `data-tour` attributes. */

export const BUILTIN_STEP_IDS = [
  "welcome",
  "org-switcher",
  "plan",
  "usage",
  "features",
  "nav-members",
  "nav-agents",
  "nav-api-keys",
  "nav-developer",
  "nav-webhooks",
  "nav-billing",
  "nav-usage",
  "nav-admin",
  "done",
] as const;

export const TOUR_ANCHORS = [
  "org-switcher",
  "plan",
  "usage",
  "features",
  "nav-dashboard",
  "nav-members",
  "nav-agents",
  "nav-api-keys",
  "nav-developer",
  "nav-webhooks",
  "nav-billing",
  "nav-usage",
  "nav-audit",
  "nav-settings",
  "nav-admin",
  "take-the-tour",
] as const;

/** Same values as nextstepjs `Step["side"]`. */
export const TOUR_SIDES = [
  "top",
  "bottom",
  "left",
  "right",
  "top-left",
  "top-right",
  "bottom-left",
  "bottom-right",
  "left-top",
  "left-bottom",
  "right-top",
  "right-bottom",
] as const;

export const TOUR_ICON_NAMES = [
  "sparkles",
  "compass",
  "building",
  "receipt",
  "gauge",
  "toggle",
  "users",
  "bot",
  "key",
  "code",
  "webhook",
  "credit-card",
  "chart",
  "shield",
  "rocket",
  "link",
  "mail",
  "file",
  "clipboard",
  "plug",
  "book",
  "lightbulb",
] as const;

export type BuiltinStepId = (typeof BUILTIN_STEP_IDS)[number];
export type TourAnchor = (typeof TOUR_ANCHORS)[number];
export type TourSide = (typeof TOUR_SIDES)[number];
export type TourIconName = (typeof TOUR_ICON_NAMES)[number];

export interface TourStepLink {
  label: string;
  href: string;
}

export interface TourStepConfig {
  id: string;
  title: string;
  content: string;
  /** Null: a centred card. */
  anchor: TourAnchor | null;
  side: TourSide | null;
  /** A built-in step id; null = just before the last step. */
  after: BuiltinStepId | null;
  /** Any-of; null = every role. */
  roles: readonly string[] | null;
  /** All-of; null = no extra gate. */
  permissions: readonly string[] | null;
  icon: TourIconName;
  link: TourStepLink | null;
}

export interface TourConfig {
  enabled: boolean;
  hide: readonly BuiltinStepId[];
  steps: readonly TourStepConfig[];
}

export const DEFAULT_TOUR: TourConfig = { enabled: true, hide: [], steps: [] };

export const MAX_TOUR_STEPS = 20;
// Raw entries read before parsing: bounds the work on a hostile payload while
// tolerating some invalid entries ahead of the valid ones.
const MAX_RAW_STEPS = MAX_TOUR_STEPS * 3;
const MAX_RAW_HIDE = BUILTIN_STEP_IDS.length * 2;
const MAX_TITLE = 80;
const MAX_CONTENT = 400;
const MAX_LINK_LABEL = 40;
const MAX_GATE_ENTRIES = 10;
// Patterns mirror src/synapse_saas/branding/models.py (StepId, RoleKey, PermissionKey).
const STEP_ID = /^[a-z][a-z0-9-]{0,40}$/;
const ROLE_KEY = /^[a-z0-9_]{2,64}$/;
const PERMISSION_KEY = /^[a-z][a-z_]*:[a-z][a-z_]*$/;
// Mirrors the API's link validation; the value lands in an href attribute.
const HTTP_URL = /^https?:\/\/[^\s<>"']+$/;
const DEL = 0x7f;
const LAST_CONTROL = 0x1f;

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function oneOf<T extends string>(values: readonly T[], value: unknown): T | null {
  return typeof value === "string" && (values as readonly string[]).includes(value)
    ? (value as T)
    : null;
}

/** The backend's SINGLE_LINE rule: no C0 control characters, no DEL. */
function isSingleLine(value: string): boolean {
  for (let i = 0; i < value.length; i += 1) {
    const code = value.charCodeAt(i);
    if (code <= LAST_CONTROL || code === DEL) return false;
  }
  return true;
}

function text(value: unknown, max: number): string | null {
  return typeof value === "string" && value.length > 0 && value.length <= max && isSingleLine(value)
    ? value
    : null;
}

/**
 * A role/permission gate. Absent or null: no gate (null). Present: 1–10
 * strings matching `pattern`, else `false` — the caller drops the step, so a
 * malformed gate fails closed like a malformed anchor.
 */
function parseGate(value: unknown, pattern: RegExp): readonly string[] | null | false {
  if (value === undefined || value === null) return null;
  if (!Array.isArray(value) || value.length === 0 || value.length > MAX_GATE_ENTRIES) return false;
  return value.every((item) => typeof item === "string" && pattern.test(item))
    ? (value as string[]).slice()
    : false;
}

function parseLink(raw: unknown): TourStepLink | null {
  if (!isObject(raw)) return null;
  const label = text(raw.label, MAX_LINK_LABEL);
  const href = typeof raw.href === "string" && HTTP_URL.test(raw.href) ? raw.href : null;
  return label && href ? { label, href } : null;
}

/** One step, or null when it cannot be shown safely (bad id, text, anchor or gate). */
function parseStep(raw: unknown): TourStepConfig | null {
  if (!isObject(raw)) return null;
  const id = typeof raw.id === "string" && STEP_ID.test(raw.id) ? raw.id : null;
  if (!id || oneOf(BUILTIN_STEP_IDS, id)) return null;
  const title = text(raw.title, MAX_TITLE);
  const content = text(raw.content, MAX_CONTENT);
  if (!title || !content) return null;
  const anchor = oneOf(TOUR_ANCHORS, raw.anchor);
  // An unknown anchor would spotlight nothing; drop rather than mis-point.
  if (raw.anchor !== undefined && raw.anchor !== null && anchor === null) return null;
  const roles = parseGate(raw.roles, ROLE_KEY);
  const permissions = parseGate(raw.permissions, PERMISSION_KEY);
  if (roles === false || permissions === false) return null;

  return {
    id,
    title,
    content,
    anchor,
    side: oneOf(TOUR_SIDES, raw.side),
    after: oneOf(BUILTIN_STEP_IDS, raw.after),
    roles,
    permissions,
    icon: oneOf(TOUR_ICON_NAMES, raw.icon) ?? "sparkles",
    link: parseLink(raw.link),
  };
}

/** Keeps the first item per key, in order (O(n)). */
function uniqueBy<T>(items: readonly T[], key: (item: T) => string): readonly T[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    const k = key(item);
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

function parseSteps(raw: unknown): readonly TourStepConfig[] {
  if (!Array.isArray(raw)) return [];
  const parsed = raw
    .slice(0, MAX_RAW_STEPS)
    .map(parseStep)
    .filter((step): step is TourStepConfig => step !== null);
  return uniqueBy(parsed, (step) => step.id).slice(0, MAX_TOUR_STEPS);
}

function parseHide(raw: unknown): readonly BuiltinStepId[] {
  if (!Array.isArray(raw)) return [];
  const ids = raw
    .slice(0, MAX_RAW_HIDE)
    .map((value) => oneOf(BUILTIN_STEP_IDS, value))
    .filter((id): id is BuiltinStepId => id !== null);
  return uniqueBy(ids, (id) => id);
}

/**
 * Validate an untrusted `tour` value. Never throws: an older API (no `tour`)
 * or a malformed one yields the default; bad steps are dropped individually.
 */
export function parseTour(raw: unknown): TourConfig {
  if (!isObject(raw)) return DEFAULT_TOUR;
  return {
    enabled: raw.enabled !== false,
    hide: parseHide(raw.hide),
    steps: parseSteps(raw.steps),
  };
}
