import Link from "next/link";

export default function LandingPage() {
  return (
    <main className="flex min-h-screen flex-col bg-zinc-950 text-zinc-100">
      <header className="mx-auto flex w-full max-w-5xl items-center justify-between px-8 py-6">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-white text-xs font-bold text-zinc-950">
            S
          </div>
          <span className="font-semibold tracking-tight">Synapse</span>
        </div>
        <nav className="flex items-center gap-6 text-sm">
          <Link href="/login" className="text-zinc-300 hover:text-white">
            Sign in
          </Link>
          <Link
            href="/register"
            className="rounded-lg bg-white px-4 py-2 font-medium text-zinc-950 hover:bg-zinc-200"
          >
            Get started
          </Link>
        </nav>
      </header>

      <section className="mx-auto flex w-full max-w-5xl flex-1 flex-col justify-center px-8 py-24">
        <p className="mb-4 text-sm font-medium uppercase tracking-widest text-zinc-500">
          Open-source SaaS framework
        </p>
        <h1 className="max-w-2xl text-5xl font-semibold leading-tight tracking-tight">
          Multi-tenancy, plans, and billing.
          <span className="text-zinc-500"> Your product is the only thing left to build.</span>
        </h1>
        <p className="mt-6 max-w-xl text-lg leading-relaxed text-zinc-400">
          Organizations, RBAC, audit, entitlements, usage metering, and pluggable
          billing — configured in YAML, not code. Clone it, define your domain,
          deploy.
        </p>
        <div className="mt-10 flex gap-4">
          <Link
            href="/register"
            className="rounded-lg bg-white px-6 py-3 text-sm font-medium text-zinc-950 hover:bg-zinc-200"
          >
            Create an account
          </Link>
          <Link
            href="/login"
            className="rounded-lg border border-zinc-700 px-6 py-3 text-sm font-medium text-zinc-200 hover:bg-zinc-900"
          >
            Sign in
          </Link>
        </div>
      </section>

      <footer className="border-t border-zinc-900 px-8 py-6 text-center text-sm text-zinc-600">
        Apache-2.0 · Synapse SaaS Framework
      </footer>
    </main>
  );
}
