"use client";

/* The deployment's mark: its logo from the API, or a letter tile in the
 * primary colour when no logo is configured. */

import { assetUrl } from "@/lib/branding";
import { useRuntimeConfig } from "@/lib/runtime-config";

const SIZES = {
  sm: { px: 28, tile: "h-7 w-7 text-xs", logo: "h-7", name: "text-sm" },
  md: { px: 32, tile: "h-8 w-8 text-sm", logo: "h-8", name: "text-base" },
  lg: { px: 56, tile: "h-14 w-14 text-2xl", logo: "h-14", name: "text-xl" },
} as const;

export function BrandMark({
  size = "md",
  showName = true,
  decorative = false,
  className = "",
}: {
  size?: keyof typeof SIZES;
  /** Render the product name next to the mark (off when a heading carries it). */
  showName?: boolean;
  /** Hide the mark from assistive tech entirely (a nearby heading names the brand). */
  decorative?: boolean;
  className?: string;
}) {
  const { apiUrl, branding } = useRuntimeConfig();
  const s = SIZES[size];
  const logo = assetUrl(apiUrl, branding.assets.logo);
  // Silent when the name is printed beside it or a heading carries it;
  // otherwise the mark itself is the brand's accessible name.
  const silent = showName || decorative;
  const alt = silent ? "" : branding.name;

  return (
    <span className={`inline-flex min-w-0 items-center gap-2.5 ${className}`}>
      {logo ? (
        // The logo is served by the API at runtime (any origin, SVG or PNG);
        // next/image would need build-time remotePatterns and a loader.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={logo}
          alt={alt}
          width={s.px}
          height={s.px}
          className={`${s.logo} w-auto shrink-0`}
        />
      ) : (
        <span
          role={silent ? undefined : "img"}
          aria-label={silent ? undefined : branding.name}
          aria-hidden={silent || undefined}
          className={`flex shrink-0 items-center justify-center rounded-lg bg-primary font-bold text-primary-foreground ${s.tile}`}
        >
          {branding.name.charAt(0).toUpperCase()}
        </span>
      )}
      {showName && (
        <span className={`truncate font-semibold tracking-tight text-zinc-900 ${s.name}`}>
          {branding.name}
        </span>
      )}
    </span>
  );
}
