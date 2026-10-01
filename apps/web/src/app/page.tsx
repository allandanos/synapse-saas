/* "/" — the deployment's front door, entirely brand-driven: mark, name,
 * tagline, the two ways in. `landing: redirect` in branding.yaml skips it. */

import Link from "next/link";
import { redirect } from "next/navigation";
import { ArrowRight } from "lucide-react";
import { BrandFooter } from "@/components/brand-footer";
import { BrandMark } from "@/components/brand-mark";
import { getRuntimeConfig } from "@/lib/runtime-config.server";

const CTA_BASE =
  "group inline-flex items-center justify-center gap-2 rounded-lg px-5 py-3 text-sm font-medium transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary active:translate-y-px";

export default async function LandingPage() {
  const { branding } = await getRuntimeConfig();
  if (branding.landing === "redirect") redirect("/login");

  return (
    <div className="flex min-h-screen flex-col bg-zinc-50">
      <div aria-hidden className="h-1 bg-primary" />
      <main className="flex flex-1 items-center px-6 py-16 sm:px-10">
        <section aria-labelledby="brand-name" className="mx-auto w-full max-w-3xl">
          <BrandMark size="lg" showName={false} decorative />
          <h1
            id="brand-name"
            className="mt-10 text-4xl font-semibold tracking-tight text-balance text-zinc-900 sm:text-6xl"
          >
            {branding.name}
          </h1>
          {branding.tagline && (
            <p className="mt-4 max-w-xl text-lg leading-relaxed text-pretty text-zinc-500 sm:text-xl">
              {branding.tagline}
            </p>
          )}
          <div className="mt-12 flex flex-col gap-3 sm:flex-row">
            <Link
              href="/login"
              className={`${CTA_BASE} bg-primary text-primary-foreground shadow-sm hover:bg-primary/90 hover:shadow-md`}
            >
              Sign in
              <ArrowRight
                className="h-4 w-4 transition-transform group-hover:translate-x-0.5"
                aria-hidden
              />
            </Link>
            <Link
              href="/register"
              className={`${CTA_BASE} border border-zinc-300 bg-white text-zinc-900 hover:border-zinc-400 hover:bg-zinc-100`}
            >
              Create account
            </Link>
          </div>
        </section>
      </main>
      <div className="px-6 pb-8 sm:px-10">
        <BrandFooter className="mx-auto max-w-3xl border-t border-zinc-200 pt-6" />
      </div>
    </div>
  );
}
