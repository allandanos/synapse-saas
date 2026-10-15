"""Per-user preference validation: key shape, patch caps, stored caps, depth."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from synapse_saas.core.errors import ValidationFailedError
from synapse_saas.identity.preferences import (
    MAX_DEPTH,
    MAX_PATCH_BYTES,
    MAX_PATCH_KEYS,
    MAX_STORED_BYTES,
    MAX_STORED_KEYS,
    check_stored_preferences,
    preferences_size,
    validate_preferences_patch,
)
from synapse_saas.identity.schemas import MeUpdate


def _nested(depth: int) -> dict[str, Any]:
    """A dict nested `depth` levels deep (depth 1 = `{"a": 1}`)."""
    value: Any = 1
    for _ in range(depth):
        value = {"a": value}
    return value  # type: ignore[no-any-return]


def _padded(size: int, key: str = "big") -> dict[str, Any]:
    """`{key: "xxx…"}` whose compact JSON is exactly `size` bytes."""
    overhead = preferences_size({key: ""})
    return {key: "x" * (size - overhead)}


class TestPatchKeys:
    @pytest.mark.parametrize("key", ["tours", "sidebar_collapsed", "a", "x-1", "a" * 64])
    def test_accepts_lowercase_keys(self, key: str) -> None:
        assert validate_preferences_patch({key: True}) == {key: True}

    @pytest.mark.parametrize("key", ["Tours", "9x", "a" * 65, "", "_x", "has space", "tours.x"])
    def test_rejects_bad_top_level_keys(self, key: str) -> None:
        with pytest.raises(ValueError, match="key"):
            validate_preferences_patch({key: True})

    def test_nested_keys_are_free_form(self) -> None:
        patch = {"tours": {"Console Welcome!": {"status": "completed"}}}
        assert validate_preferences_patch(patch) == patch

    def test_rejects_too_many_keys(self) -> None:
        patch = {f"k{i}": i for i in range(MAX_PATCH_KEYS + 1)}
        with pytest.raises(ValueError, match="keys"):
            validate_preferences_patch(patch)

    def test_accepts_the_key_limit(self) -> None:
        patch = {f"k{i}": i for i in range(MAX_PATCH_KEYS)}
        assert validate_preferences_patch(patch) == patch


class TestPatchSizeAndDepth:
    def test_rejects_over_the_byte_cap(self) -> None:
        with pytest.raises(ValueError, match="bytes"):
            validate_preferences_patch(_padded(MAX_PATCH_BYTES + 1))

    def test_accepts_the_byte_cap(self) -> None:
        patch = _padded(MAX_PATCH_BYTES)
        assert preferences_size(patch) == MAX_PATCH_BYTES
        assert validate_preferences_patch(patch) == patch

    def test_bytes_count_utf8_not_characters(self) -> None:
        # "é" is two bytes in UTF-8; a character count would let this through.
        overhead = preferences_size({"big": ""})
        with pytest.raises(ValueError, match="bytes"):
            validate_preferences_patch({"big": "é" * ((MAX_PATCH_BYTES - overhead) // 2 + 1)})

    def test_rejects_depth_nine(self) -> None:
        with pytest.raises(ValueError, match="deep"):
            validate_preferences_patch({"x": _nested(MAX_DEPTH)})

    def test_accepts_depth_eight(self) -> None:
        patch = {"x": _nested(MAX_DEPTH - 1)}
        assert validate_preferences_patch(patch) == patch

    def test_lists_count_towards_depth(self) -> None:
        with pytest.raises(ValueError, match="deep"):
            validate_preferences_patch({"x": [[[[[[[[1]]]]]]]]})

    def test_rejects_a_non_object(self) -> None:
        # ValueError, not TypeError: only ValueError becomes a pydantic 422.
        with pytest.raises(ValueError, match="object"):
            validate_preferences_patch(["tours"])

    def test_returns_a_copy(self) -> None:
        patch = {"tours": {}}
        assert validate_preferences_patch(patch) is not patch


class TestStoredCaps:
    def test_passes_at_the_key_boundary(self) -> None:
        check_stored_preferences({f"k{i}": i for i in range(MAX_STORED_KEYS)})

    def test_raises_over_the_key_cap(self) -> None:
        with pytest.raises(ValidationFailedError):
            check_stored_preferences({f"k{i}": i for i in range(MAX_STORED_KEYS + 1)})

    def test_passes_at_the_byte_boundary(self) -> None:
        check_stored_preferences(_padded(MAX_STORED_BYTES))

    def test_raises_over_the_byte_cap(self) -> None:
        with pytest.raises(ValidationFailedError):
            check_stored_preferences(_padded(MAX_STORED_BYTES + 1))


class TestMeUpdateSchema:
    def test_preferences_is_optional(self) -> None:
        assert MeUpdate().preferences is None

    def test_bad_key_is_a_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            MeUpdate(preferences={"Tours": {}})

    def test_valid_patch_round_trips(self) -> None:
        assert MeUpdate(preferences={"tours": {}}).preferences == {"tours": {}}


def _deep_list(levels: int) -> Any:
    value: Any = []
    for _ in range(levels):
        value = [value]
    return value


HOSTILE_JSON = (
    '{"preferences":{"a":NaN}}',
    '{"preferences":{"a":1e999}}',
    '{"preferences":{"a":"\\u0000"}}',
)


class TestHostileValues:
    """What JSON or Postgres JSONB cannot hold must be a 422 at parse time, never a 500."""

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_numbers_are_rejected(self, value: float) -> None:
        with pytest.raises(ValueError, match="finite"):
            validate_preferences_patch({"a": value})

    def test_non_finite_numbers_are_rejected_when_nested(self) -> None:
        with pytest.raises(ValueError, match="finite"):
            validate_preferences_patch({"a": [1, {"b": float("nan")}]})

    @pytest.mark.parametrize("value", ["\x00", "a\x00b", {"k": "\x00"}, ["\x00"], {"k\x00": 1}])
    def test_nul_characters_are_rejected(self, value: Any) -> None:
        with pytest.raises(ValueError, match="NUL"):
            validate_preferences_patch({"a": value})

    def test_a_trailing_newline_in_a_key_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="must match"):
            validate_preferences_patch({"a\n": 1})

    @pytest.mark.parametrize("levels", [MAX_DEPTH + 1, 600, 5000])
    def test_pathological_nesting_is_a_value_error_not_a_recursion_error(self, levels: int) -> None:
        with pytest.raises(ValueError, match="deeper"):
            validate_preferences_patch({"a": _deep_list(levels)})

    def test_a_non_object_patch_is_a_value_error(self) -> None:
        with pytest.raises(ValueError, match="object"):
            validate_preferences_patch(["not", "an", "object"])

    def test_the_stored_check_rejects_non_finite_numbers(self) -> None:
        with pytest.raises(ValidationFailedError):
            check_stored_preferences({"a": float("inf")})

    @pytest.mark.parametrize("raw", HOSTILE_JSON)
    def test_the_schema_turns_hostile_json_into_validation_errors(self, raw: str) -> None:
        with pytest.raises(ValidationError):
            MeUpdate.model_validate_json(raw)
