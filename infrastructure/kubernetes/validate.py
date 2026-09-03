#!/usr/bin/env python3
"""Structural validation for the k8s manifests without a live cluster.

kubectl needs an API server for discovery even with --validate=false; this
checks what actually breaks deployments: YAML parse, kind-shape (required
fields per kind), namespace consistency, selector↔label wiring, and probe
paths. Run: python3 validate.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REQUIRED = {
    "Namespace": ["metadata.name"],
    "ConfigMap": ["metadata.name", "data"],
    "Secret": ["metadata.name"],
    "Deployment": ["metadata.name", "spec.selector.matchLabels", "spec.template"],
    "Service": ["metadata.name", "spec.selector", "spec.ports"],
    "Job": ["metadata.name", "spec.template"],
    "HorizontalPodAutoscaler": ["metadata.name", "spec.scaleTargetRef", "spec.metrics"],
    "Ingress": ["metadata.name", "spec.rules"],
}

KIND_ALIASES = {"hpa": "HorizontalPodAutoscaler"}


def dig(obj: object, dotted: str) -> object:
    cur: object = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def validate_file(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        docs = [d for d in yaml.safe_load_all(path.read_text()) if d]
    except yaml.YAMLError as exc:
        return [f"{path.name}: invalid YAML: {exc}"]

    for i, doc in enumerate(docs, 1):
        kind = doc.get("kind") or doc.get("kind")
        if doc.get("apiVersion", "").endswith("/v2") and kind == "HorizontalPodAutoscaler":
            pass
        kind = doc.get("kind")
        if not kind:
            errors.append(f"{path.name}[{i}]: missing kind")
            continue

        for field in REQUIRED.get(kind, ["metadata.name"]):
            if dig(doc, field) is None:
                errors.append(f"{path.name}[{i}] {kind}: missing {field}")

        meta = doc.get("metadata", {})
        if meta.get("namespace") and meta["namespace"] != "synapse":
            errors.append(f"{path.name}[{i}] {kind}: namespace {meta['namespace']!r} != 'synapse'")

        # selector ↔ labels wiring for Deployment
        if kind == "Deployment":
            selector = dig(doc, "spec.selector.matchLabels") or {}
            labels = dig(doc, "spec.template.metadata.labels") or {}
            for key, value in selector.items():
                if labels.get(key) != value:
                    errors.append(
                        f"{path.name}[{i}] Deployment: selector {key}={value!r} "
                        f"not matched by pod labels {labels!r}"
                    )
            for container in dig(doc, "spec.template.spec.containers") or []:
                for probe_name in ("readinessProbe", "livenessProbe"):
                    probe = container.get(probe_name)
                    if probe and not dig(probe, "httpGet.path"):
                        errors.append(f"{path.name}[{i}]: {probe_name} without httpGet.path")

        # Service selector matches some Deployment's labels (cross-file, checked later)
    return errors


def cross_file_checks(all_docs: list[tuple[str, dict]]) -> list[str]:
    errors: list[str] = []
    deployments: dict[str, dict] = {}
    services: list[dict] = []
    for name, doc in all_docs:
        if doc.get("kind") == "Deployment":
            deployments[doc["metadata"]["name"]] = doc
        elif doc.get("kind") == "Service":
            services.append(doc)

    for svc in services:
        selector = (svc.get("spec", {}).get("selector") or {})
        matched = any(
            all(
                (dig(d, "spec.template.metadata.labels") or {}).get(k) == v
                for k, v in selector.items()
            )
            for d in deployments.values()
        )
        if not matched:
            errors.append(f"Service {svc['metadata']['name']}: selector matches no Deployment")

    hpa_targets = {
        doc["spec"]["scaleTargetRef"]["name"]: doc["spec"]["scaleTargetRef"]["kind"]
        for _, doc in all_docs
        if doc.get("kind") == "HorizontalPodAutoscaler"
    }
    for target, kind in hpa_targets.items():
        actual = deployments.get(target)
        if actual is None:
            errors.append(f"HPA targets unknown {kind} {target!r}")
    return errors


def main() -> int:
    root = Path(__file__).parent
    files = sorted(root.glob("*.yaml"))
    all_errors: list[str] = []
    all_docs: list[tuple[str, dict]] = []

    for path in files:
        all_errors.extend(validate_file(path))
        try:
            for doc in (d for d in yaml.safe_load_all(path.read_text()) if d):
                all_docs.append((path.name, doc))
        except yaml.YAMLError:
            pass  # already reported

    all_errors.extend(cross_file_checks(all_docs))

    if all_errors:
        for error in all_errors:
            print(f"FAIL {error}")
        return 1
    print(f"OK — {len(files)} files, {len(all_docs)} objects: parse, shape, namespace,")
    print("   selector wiring, HPA targets, and probe paths all consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
