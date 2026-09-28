"""Root conftest: the framework's own suite consumes the PUBLIC test plugin
(`synapse_saas.testing.fixtures`) so it can never drift from what products get."""

pytest_plugins = ["synapse_saas.testing.fixtures"]
