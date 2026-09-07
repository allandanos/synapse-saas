"""Agent registry — governance and billing for org-scoped agents (ADR 0007).

This framework registers agents, gates them behind entitlements, meters their
usage, and bills for it. It does not execute them — that is the agentic
runtime's job. See docs/adr/0007-agents-governance-not-execution.md.
"""
