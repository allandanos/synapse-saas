"""Console entrypoints: synapse-api, synapse-worker, synapse-cli."""

from __future__ import annotations


def run_api() -> None:
    """synapse-api — uvicorn launcher. Binds all interfaces: containers expect it."""
    import uvicorn

    uvicorn.run(
        "synapse_saas.api.app:create_app",
        factory=True,
        host="0.0.0.0",  # noqa: S104 — containerized deployment boundary
        port=8000,
        reload=False,
    )


def run_worker() -> None:
    """synapse-worker — arq worker launcher."""
    from arq import run_worker

    from synapse_saas.worker.jobs import WorkerSettings

    run_worker(WorkerSettings)  # type: ignore[arg-type]
