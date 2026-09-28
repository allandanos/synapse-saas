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


@cli.command("new")
@click.argument("name", required=False)
@click.option("--template", default="hello-saas", show_default=True, help="Project template")
@click.option("--dir", "directory", default=".", show_default=True, help="Parent directory")
@click.option(
    "--framework-path",
    default=None,
    help="Depend on a local checkout of the framework instead of PyPI (uv path source)",
)
@click.option("--list-templates", "list_only", is_flag=True, help="List templates and exit")
def new_project(
    name: str | None, template: str, directory: str, framework_path: str | None, list_only: bool
) -> None:
    """Generate a product that depends on the framework (ADR 0011).

    The project gets its own package, an Alembic branch that depends on the
    framework head, tests on the public pytest plugin, and a compose stack.
    """
    from pathlib import Path

    from synapse_saas.scaffold import generate, list_templates

    if list_only:
        for info in list_templates():
            click.echo(f"{info.name:<14} {info.description}")
        return
    if not name:
        raise click.UsageError("NAME is required (e.g. `synapse-cli new my-product`)")
    destination = Path(directory) / name
    try:
        written = generate(name, destination=destination, template=template, framework_path=framework_path)
    except (ValueError, FileExistsError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Created {destination} ({len(written)} files) from template {template!r}.")
    click.echo(
        "Next: cd " + str(destination) + " && uv sync && cp .env.example .env && make migrate seed dev"
    )


@cli.group()
def authz() -> None:
    """Fine-grained authorization (OpenFGA) — model bootstrap, tuple sync, checks."""


@authz.group()
def fga() -> None:
    """OpenFGA store operations (SYNAPSE_OPENFGA_URL)."""


@fga.command("write-model")
@click.option("--create-store", "store_name", default=None, help="Create a store with this name first")
@click.option("--dsl", is_flag=True, help="Print the model as DSL instead of writing it")
def fga_write_model(store_name: str | None, dsl: bool) -> None:
    """Write the catalog-generated authorization model to the store."""
    from synapse_saas.authorization.fga_model import build_model, render_dsl

    if dsl:
        click.echo(render_dsl())
        return

    async def _run() -> tuple[str, str]:
        from synapse_saas.authorization.fga import FgaClient

        client = FgaClient()
        if store_name:
            client.store_id = await client.create_store(store_name)
        model_id = await client.write_model(build_model())
        return client.store_id, model_id

    store_id, model_id = asyncio.run(_run())
    click.echo(f"store_id={store_id}")
    click.echo(f"authorization_model_id={model_id}")
    click.echo("Set SYNAPSE_OPENFGA_STORE_ID / SYNAPSE_OPENFGA_MODEL_ID accordingly.")


@fga.command("sync")
@click.option("--all", "sync_all", is_flag=True, help="Every active membership")
@click.option("--org", "org_id", default=None, help="Only this organization id")
def fga_sync(sync_all: bool, org_id: str | None) -> None:
    """Converge OpenFGA tuples to the RBAC state (backfill or repair)."""
    if not sync_all and not org_id:
        raise click.UsageError("Pass --all or --org <id>")

    async def _run() -> int:
        from sqlalchemy import select

        from synapse_saas.authorization.sync import apply_tuple_sync
        from synapse_saas.core.db import dispose_engine, get_owner_session_factory
        from synapse_saas.tenancy.models import Membership

        try:
            async with get_owner_session_factory()() as session:
                stmt = select(Membership.organization_id, Membership.user_id).where(
                    Membership.user_id.is_not(None)
                )
                if org_id:
                    stmt = stmt.where(Membership.organization_id == org_id)
                pairs = (await session.execute(stmt)).all()
            count = 0
            for organization_id, user_id in pairs:
                await apply_tuple_sync({"organization_id": str(organization_id), "user_id": str(user_id)})
                count += 1
            return count
        finally:
            await dispose_engine()

    click.echo(f"synced {asyncio.run(_run())} membership(s)")


@fga.command("check")
@click.argument("user_id")
@click.argument("organization_id")
@click.argument("permission")
def fga_check(user_id: str, organization_id: str, permission: str) -> None:
    """Ask the store: may USER exercise PERMISSION in ORGANIZATION?"""

    async def _run() -> bool:
        from synapse_saas.authorization.fga import FgaClient
        from synapse_saas.authorization.fga_model import relation_for

        return await FgaClient().check(
            f"user:{user_id}", relation_for(permission), f"organization:{organization_id}"
        )

    allowed = asyncio.run(_run())
    click.echo("allowed" if allowed else "denied")
    if not allowed:
        raise SystemExit(1)


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
