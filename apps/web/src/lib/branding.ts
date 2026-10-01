/* Deployment branding as served by the API's `GET /v1/branding`.
 *
 * Isomorphic: the server parses it (runtime-config.server.ts), the client
 * reads it from context (runtime-config.tsx). Asset URLs are origin-relative
 * on purpose — prefix them with the PUBLIC API URL via `assetUrl()`. */

export interface BrandAssets {
  logo: string | null;
  logo_dark: string | null;
  favicon: string | null;
  custom_css: string | null;
}

export interface BrandColors {
  primary: string;
  primary_foreground: string;
  accent: string;
  radius: string;
}

export interface BrandLinks {
  website: string | null;
  docs: string | null;
  terms: string | null;
  privacy: string | null;
  support_email: string | null;
}

export interface Branding {
  name: string;
  tagline: string | null;
  assets: BrandAssets;
  colors: BrandColors;
  links: BrandLinks;
  landing: "page" | "redirect";
  powered_by: boolean;
}

/**
 * Neutral fallback while the API is unreachable. Deliberately NOT the Synapse
 * brand: a white-labelled deployment must never flash the framework's name.
 */
export const DEFAULT_BRANDING: Branding = {
  name: "Console",
  tagline: null,
  assets: { logo: null, logo_dark: null, favicon: null, custom_css: null },
  colors: {
    primary: "#18181b",
    primary_foreground: "#ffffff",
    accent: "#2563eb",
    radius: "0.5rem",
  },
  links: { website: null, docs: null, terms: null, privacy: null, support_email: null },
  landing: "page",
  powered_by: false,
};

const HEX_COLOR = /^#[0-9a-fA-F]{6}$/;
const RADIUS = /^\d+(\.\d+)?(px|rem|em)$/;
// Mirrors the API's BrandLinks validation; these values land in href attributes.
const HTTP_URL = /^https?:\/\/[^\s<>"']+$/;
// Strict on purpose: the address is interpolated into a mailto: link.
const EMAIL = /^[^\s@<>"'?&]+@[^\s@<>"'?&]+$/;
// Origin-relative API path only: these values end up in href/src attributes.
const ASSET_PATH = /^\/v1\/branding\/assets\/[A-Za-z0-9][A-Za-z0-9._-]{0,63}(\?v=[0-9a-f]+)?$/;

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function str(value: unknown, pattern?: RegExp): string | null {
  if (typeof value !== "string" || value.length === 0) return null;
  return pattern && !pattern.test(value) ? null : value;
}

function pick<T extends object>(
  defaults: T,
  raw: unknown,
  patterns: Partial<Record<keyof T, RegExp>>,
  nullable: boolean,
): T {
  const source = isObject(raw) ? raw : {};
  return Object.fromEntries(
    (Object.keys(defaults) as (keyof T & string)[]).map((key) => {
      const value = str(source[key], patterns[key]);
      return [key, value ?? (nullable ? null : defaults[key])];
    }),
  ) as T;
}

/**
 * Validate an untrusted `/v1/branding` payload. Throws when the payload isn't
 * branding at all (no name); otherwise drops individual bad fields to their
 * neutral defaults — these values are interpolated into CSS and attributes.
 */
export function parseBranding(raw: unknown): Branding {
  if (!isObject(raw)) throw new Error("branding: expected a JSON object");
  const name = str(raw.name);
  if (!name) throw new Error("branding: missing name");

  return {
    name,
    tagline: str(raw.tagline),
    assets: pick(
      DEFAULT_BRANDING.assets,
      raw.assets,
      { logo: ASSET_PATH, logo_dark: ASSET_PATH, favicon: ASSET_PATH, custom_css: ASSET_PATH },
      true,
    ),
    colors: pick(
      DEFAULT_BRANDING.colors,
      raw.colors,
      { primary: HEX_COLOR, primary_foreground: HEX_COLOR, accent: HEX_COLOR, radius: RADIUS },
      false,
    ),
    links: pick(
      DEFAULT_BRANDING.links,
      raw.links,
      {
        website: HTTP_URL,
        docs: HTTP_URL,
        terms: HTTP_URL,
        privacy: HTTP_URL,
        support_email: EMAIL,
      },
      true,
    ),
    landing: raw.landing === "redirect" ? "redirect" : "page",
    powered_by: raw.powered_by !== false,
  };
}

/** Absolute URL of a branding asset for the browser, or null when unset. */
export function assetUrl(apiUrl: string, path: string | null): string | null {
  return path ? `${apiUrl}${path}` : null;
}

/** The `--brand-*` custom properties set on <html>; globals.css maps them to tokens. */
export function brandCssVariables(colors: BrandColors): Record<string, string> {
  return {
    "--brand-primary": colors.primary,
    "--brand-primary-foreground": colors.primary_foreground,
    "--brand-accent": colors.accent,
    "--brand-radius": colors.radius,
  };
}
