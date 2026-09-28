"""synapse-cli: migrate, seed, plans sync, on-demand jobs."""

from __future__ import annotations

import asyncio

import click
from alembic.config import Config


@click.group()
def cli() -> None:
    """Synapse SaaS Framework management commands (run as the schema owner)."""


@cli.command()
def migrate() -> None:
    """Apply Alembic migrations."""
    from alembic import command

    command.upgrade(alembic_config(), "head")
    click.echo("Migrations applied.")


def alembic_config() -> Config:
    """Alembic config bound to the PACKAGED migrations — works from any cwd,
    installed from PyPI or a checkout alike."""
    import importlib.resources

    ini = importlib.resources.files("synapse_saas") / "migrations" / "alembic.ini"
    return Config(str(ini))


@cli.command()
@click.option("--dev", is_flag=True, help="Also seed demo org/users (never in production)")
def seed(dev: bool) -> None:
    """Seed permissions, system roles, and sync the plan catalog."""
    asyncio.run(_seed(dev))


async def _seed(dev: bool) -> None:
    from synapse_saas.core.config import get_settings
    from synapse_saas.core.db import get_owner_session_factory
    from synapse_saas.core.logging import configure_logging
    from synapse_saas.seeds import seed_dev, seed_system
    from synapse_saas.seeds.dev_seed import DEV_PASSWORD
    from synapse_saas.subscriptions.catalog import load_catalog
    from synapse_saas.subscriptions.sync import sync_plans

    configure_logging()
    settings = get_settings()

    factory = get_owner_session_factory()
    async with factory() as session:
        counts = await seed_system(session)
        catalog = load_catalog()
        result = await sync_plans(session, catalog)
        if dev and not settings.is_production:
            await seed_dev(session)
        await session.commit()

    click.echo(
        f"Seeded {counts['permissions']} permissions, {counts['system_roles']} system roles; "
        f"plans: +{result.plans_added} new, ~{result.plans_updated} updated."
    )
    if dev and not settings.is_production:
        click.echo(
            f"Dev data: owner@/admin@/billing@/developer@/member@acme.example.com — all use / {DEV_PASSWORD}"
        )


@cli.group()
def db() -> None:
    """Database role operations."""


@db.command("provision-app-role")
@click.option(
    "--role", default="synapse_app", show_default=True, help="Subject (non-owner) login role for the API"
)
@click.option(
    "--password",
    envvar="SYNAPSE_APP_ROLE_PASSWORD",
    required=True,
    help="Password for the role (or set SYNAPSE_APP_ROLE_PASSWORD)",
)
def provision_app_role(role: str, password: str) -> None:
    """Create/refresh the RLS-subject role the API connects as.

    Run as the schema owner (worker/CLI DSN). Point SYNAPSE_DATABASE_URL at the
    new role and set SYNAPSE_TENANT_ISOLATION=app_and_rls; keep
    SYNAPSE_WORKER_DATABASE_URL on the owner for the worker, CLI, and migrations.
    """
    from synapse_saas.core import db as core_db

    try:
        asyncio.run(core_db.provision_app_role(core_db.get_owner_engine(), role, password))
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="--role") from exc
    click.echo(f"Role {role!r} provisioned: LOGIN NOBYPASSRLS, DML on public schema, default privileges set.")


@cli.group()
def jobs() -> None:
    """Run worker jobs on demand (Cloud Run / Cloud Scheduler, one-off maintenance)."""


JOB_NAMES = (
    "dispatch_outbox",
    "deliver_webhooks",
    "rollup_usage",
    "expire_entitlements",
    "advance_recurring_billing",
    "ensure_partitions",
    "purge_expired",
)


@jobs.command("run-once")
@click.argument("names", nargs=-1)
@click.option("--all", "run_all", is_flag=True, help="Run every cron job once, in dispatch order")
def jobs_run_once(names: tuple[str, ...], run_all: bool) -> None:
    """Await each named job exactly once and exit — what a scheduler-triggered
    Cloud Run job executes instead of the always-on arq loop."""
    selected = list(JOB_NAMES) if run_all else list(names)
    if not selected:
        raise click.UsageError("Name at least one job or pass --all. Known: " + ", ".join(JOB_NAMES))
    unknown = [n for n in selected if n not in JOB_NAMES]
    if unknown:
        raise click.UsageError(f"Unknown job(s): {', '.join(unknown)}. Known: {', '.join(JOB_NAMES)}")
    results = asyncio.run(_run_jobs_once(selected))
    for name, outcome in results.items():
        click.echo(f"{name}: {outcome}")
    if any(str(v).startswith("error") for v in results.values()):
        raise SystemExit(1)


async def _run_jobs_once(names: list[str]) -> dict[str, object]:
    from synapse_saas.core.db import dispose_engine
    from synapse_saas.core.http import close_http_client
    from synapse_saas.worker import jobs as job_module

    results: dict[str, object] = {}
    try:
        for name in names:
            fn = getattr(job_module, name)
            try:
                results[name] = await fn({})
            except Exception as exc:  # report, keep going: one job must not hide the others
                results[name] = f"error: {exc}"
    finally:
        await close_http_client()
        await dispose_engine()
    return results


@cli.group()
def plans() -> None:
    """Plan catalog operations."""


@plans.command()
@click.option("--provider", default=None, help="Also push catalog to this provider (stripe)")
@click.option("--apply", is_flag=True, help="Actually write remote products/prices (default: dry-run)")
def sync(provider: str | None, apply: bool) -> None:
    """Sync config/plans.yaml to the database (and optionally to a provider)."""
    asyncio.run(_sync_plans(provider, apply))


async def _sync_plans(provider: str | None, apply: bool) -> None:

    from synapse_saas.core.db import get_owner_session_factory
    from synapse_saas.subscriptions.catalog import load_catalog
    from synapse_saas.subscriptions.sync import sync_plans

    factory = get_owner_session_factory()
    catalog = load_catalog()
    async with factory() as session:
        result = await sync_plans(session, catalog)
        await session.commit()
    click.echo(
        f"features +{result.features_added}, metrics +{result.metrics_added}, "
        f"plans +{result.plans_added}/~{result.plans_updated}/archived {result.plans_archived}"
    )

    if provider:
        await _push_provider_catalog(provider, apply)


async def _push_provider_catalog(provider_name: str, apply: bool) -> None:
    from sqlalchemy import select

    from synapse_saas.core.db import get_owner_session_factory
    from synapse_saas.subscriptions.catalog import load_catalog
    from synapse_saas.subscriptions.models import Plan

    factory = get_owner_session_factory()
    async with factory() as session:
        catalog = load_catalog()
        for plan_def in catalog.plans:
            if plan_def.price_cents is None:
                continue  # custom-priced plans have nothing to push
            if not apply:
                # Dry-run needs no credentials — it only describes the diff
                click.echo(
                    f"[dry-run] {provider_name}: upsert product+price for "
                    f"{plan_def.key} ({plan_def.price_cents} minor units)"
                )
                continue

            from synapse_saas.billing.protocol import BillingCapability
            from synapse_saas.billing.registry import build_provider

            provider = build_provider(provider_name)
            if BillingCapability.PLAN_SYNC not in provider.supports:
                click.echo(f"{provider_name} does not support plan sync; skipping")
                return
            refs = await provider.upsert_product_and_price(  # type: ignore[attr-defined]
                plan_key=plan_def.key,
                plan_name=plan_def.name,
                price_cents=plan_def.price_cents,
                currency=plan_def.currency or catalog.defaults.currency,
                interval=plan_def.interval or catalog.defaults.interval,
            )
            plan = (await session.execute(select(Plan).where(Plan.key == plan_def.key))).scalar_one()
            merged = {**plan.provider_refs, provider_name: refs}
            plan.provider_refs = merged
            click.echo(f"{provider_name}: {plan_def.key} → {refs}")
        if apply:
            await session.commit()


if __name__ == "__main__":
    cli()
