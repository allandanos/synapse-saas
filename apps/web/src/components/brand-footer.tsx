"use client";

/* Footer for the public surfaces (landing + auth): the brand's links that are
 * set, plus "Powered by Synapse" unless the deployment opts out. */

import { useBranding } from "@/lib/runtime-config";

const FRAMEWORK_URL = "https://github.com/allandanos/synapse-saas";

const LINK_CLASS =
  "rounded-sm text-zinc-500 underline-offset-4 transition-colors hover:text-zinc-900 hover:underline";

export function BrandFooter({ className = "" }: { className?: string }) {
  const { links, powered_by } = useBranding();
  const items = [
    { label: "Website", href: links.website },
    { label: "Docs", href: links.docs },
    { label: "Terms", href: links.terms },
    { label: "Privacy", href: links.privacy },
    { label: "Support", href: links.support_email ? `mailto:${links.support_email}` : null },
  ].filter((item): item is { label: string; href: string } => Boolean(item.href));

  if (items.length === 0 && !powered_by) return null;

  return (
    <footer
      className={`flex flex-col-reverse gap-3 text-xs sm:flex-row sm:items-center sm:justify-between ${className}`}
    >
      {powered_by ? (
        <a href={FRAMEWORK_URL} target="_blank" rel="noopener noreferrer" className={LINK_CLASS}>
          Powered by Synapse
        </a>
      ) : (
        <span />
      )}
      {items.length > 0 && (
        <nav aria-label="Legal and support" className="flex flex-wrap gap-x-5 gap-y-2">
          {items.map((item) => (
            <a
              key={item.label}
              href={item.href}
              target={item.href.startsWith("mailto:") ? undefined : "_blank"}
              rel="noopener noreferrer"
              className={LINK_CLASS}
            >
              {item.label}
            </a>
          ))}
        </nav>
      )}
    </footer>
  );
}
