/* Shared frame for the public auth pages (login, register, forgot/reset
 * password): brand mark above a single card, brand footer below. The route
 * group keeps URLs unchanged; each page renders only its own content. */

import Link from "next/link";
import { BrandFooter } from "@/components/brand-footer";
import { BrandMark } from "@/components/brand-mark";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col bg-zinc-50">
      <div aria-hidden className="h-1 bg-primary" />
      <main className="flex flex-1 flex-col items-center justify-center px-4 py-12 sm:py-16">
        <div className="w-full max-w-sm">
          <Link href="/" className="mb-8 inline-flex max-w-full rounded-lg">
            <BrandMark size="md" />
          </Link>
          <div className="rounded-xl border border-zinc-200 bg-white p-6 shadow-sm shadow-zinc-900/5 sm:p-8">
            {children}
          </div>
        </div>
      </main>
      <div className="px-4 pb-8">
        <BrandFooter className="mx-auto max-w-sm" />
      </div>
    </div>
  );
}
