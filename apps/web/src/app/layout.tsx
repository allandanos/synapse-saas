import type { CSSProperties } from "react";
import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { assetUrl, brandCssVariables } from "@/lib/branding";
import { RuntimeConfigProvider } from "@/lib/runtime-config";
import { getRuntimeConfig } from "@/lib/runtime-config.server";

// Rendered per request: the API URL and the brand are runtime configuration,
// so `next build` never contacts the API and one image serves any deployment.
export const dynamic = "force-dynamic";

export async function generateMetadata(): Promise<Metadata> {
  const { apiUrl, branding } = await getRuntimeConfig();
  const favicon = assetUrl(apiUrl, branding.assets.favicon);
  return {
    title: { default: branding.name, template: `%s · ${branding.name}` },
    description: branding.tagline ?? `${branding.name} console`,
    ...(favicon ? { icons: { icon: favicon } } : {}),
  };
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const { apiUrl, branding } = await getRuntimeConfig();
  const customCss = assetUrl(apiUrl, branding.assets.custom_css);

  return (
    <html lang="en" style={brandCssVariables(branding.colors) as CSSProperties}>
      <head>
        {customCss && (
          // Operator stylesheet served by the API, linked after the app's CSS
          // so it can override anything. CSS imports can't load a runtime URL,
          // hence a plain <link>.
          <link rel="stylesheet" href={customCss} />
        )}
      </head>
      <body className="min-h-screen antialiased">
        <RuntimeConfigProvider config={{ apiUrl, branding }}>
          <Providers>{children}</Providers>
        </RuntimeConfigProvider>
      </body>
    </html>
  );
}
