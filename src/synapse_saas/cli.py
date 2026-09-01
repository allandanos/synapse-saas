"""synapse-cli: migrate, seed, plans sync."""

from __future__ import annotations

import asyncio

import click


@click.group()
def cli() -> None:
    """Synapse SaaS Framework management commands."""


@cli.command()
def migrate() -> None:
    """Apply Alembic migrations."""
    from alembic import command
    from alembic.config import Config

    config = Config("database/alembic.ini")
    command.upgrade(config, "head")
    click.echo("Migrations applied.")


@cli.command()
@click.option("--dev", is_flag=True, help="Also seed demo org/users (never in production)")
def seed(dev: bool) -> None:
    """Seed permissions, system roles, and sync the plan catalog."""
    asyncio.run(_seed(dev))


async def _seed(dev: bool) -> None:
    from synapse_saas.core.config import get_settings
    from synapse_saas.core.db import get_session_factory
    from synapse_saas.core.logging import configure_logging
    from synapse_saas.seeds import seed_dev, seed_system
    from synapse_saas.subscriptions.catalog import load_catalog
    from synapse_saas.subscriptions.sync import sync_plans

    configure_logging()
    settings = get_settings()

    factory = get_session_factory()
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
        click.echo("Dev data: owner@acme.test / password123 (member@acme.test too)")


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

    from synapse_saas.core.db import get_session_factory
    from synapse_saas.subscriptions.catalog import load_catalog
    from synapse_saas.subscriptions.sync import sync_plans

    factory = get_session_factory()
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

    from synapse_saas.core.db import get_session_factory
    from synapse_saas.subscriptions.catalog import load_catalog
    from synapse_saas.subscriptions.models import Plan

    factory = get_session_factory()
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
            refs = await provider.upsert_product_and_price(
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
