"""Branding loader: file → validated kit, all errors at once, asset containment."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from synapse_saas.branding.loader import (
    asset_media_type,
    get_branding,
    load_branding,
    write_starter_kit,
)
from synapse_saas.core.errors import BrandingInvalidError, NotFoundError

REPO_ROOT = Path(__file__).resolve().parents[3]
REPO_KIT = REPO_ROOT / "config" / "branding"
# Copies of the default kit that ship elsewhere: the published-images compose kit
# and the scaffold (whose branding.yaml is a template with `name: $package_title`).
COMPOSE_KIT = REPO_ROOT / "deploy" / "compose" / "branding"
SCAFFOLD_KIT = REPO_ROOT / "src" / "synapse_saas" / "scaffold" / "templates" / "hello-saas" / "branding"


def _kit(tmp_path: Path, yaml_text: str, files: dict[str, bytes] | None = None) -> Path:
    path = tmp_path / "branding.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    for name, content in (files or {}).items():
        (tmp_path / name).write_bytes(content)
    return path


class TestLoad:
    def test_packaged_default_loads(self) -> None:
        brand = load_branding(REPO_KIT / "branding.yaml")
        assert brand.name == "Synapse"
        assert brand.powered_by is True
        assert brand.served_assets == {"logo": "logo.svg", "favicon": "favicon.svg"}

    def test_digest_is_sha256_prefix_and_rides_the_url(self, tmp_path: Path) -> None:
        content = b"<svg xmlns='http://www.w3.org/2000/svg'/>"
        brand = load_branding(
            _kit(tmp_path, "version: 1\nname: Acme\nlogo: mark.svg\n", {"mark.svg": content})
        )
        digest = hashlib.sha256(content).hexdigest()[:8]
        assert brand.asset_digest("mark.svg") == digest
        assert brand.asset_url("mark.svg") == f"/v1/branding/assets/mark.svg?v={digest}"

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(BrandingInvalidError) as excinfo:
            load_branding(tmp_path / "nope.yaml")
        assert excinfo.value.title == "branding_invalid"
        assert "not found" in excinfo.value.message

    def test_bad_yaml(self, tmp_path: Path) -> None:
        with pytest.raises(BrandingInvalidError, match="not valid YAML"):
            load_branding(_kit(tmp_path, "version: 1\nname: [unclosed\n"))

    def test_non_utf8_file_is_a_branding_error(self, tmp_path: Path) -> None:
        path = tmp_path / "branding.yaml"
        path.write_bytes(b"version: 1\nname: \xff\xfe\n")
        with pytest.raises(BrandingInvalidError, match="could not be read"):
            load_branding(path)

    def test_unreadable_file_is_a_branding_error(self, tmp_path: Path) -> None:
        path = _kit(tmp_path, "version: 1\nname: Acme\n")
        path.chmod(0)
        try:
            if os.access(path, os.R_OK):
                pytest.skip("running with privileges that ignore file modes")
            with pytest.raises(BrandingInvalidError, match="could not be read"):
                load_branding(path)
        finally:
            path.chmod(0o644)

    def test_unreadable_asset_is_reported(self, tmp_path: Path) -> None:
        path = _kit(tmp_path, "version: 1\nname: Acme\nlogo: logo.svg\n", {"logo.svg": b"<svg/>"})
        (tmp_path / "logo.svg").chmod(0)
        try:
            if os.access(tmp_path / "logo.svg", os.R_OK):
                pytest.skip("running with privileges that ignore file modes")
            with pytest.raises(BrandingInvalidError) as excinfo:
                load_branding(path)
            assert any("could not be read: logo.svg" in e for e in excinfo.value.extras["errors"])
        finally:
            (tmp_path / "logo.svg").chmod(0o644)

    def test_relative_path_is_anchored_at_load_time(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _kit(tmp_path, "version: 1\nname: Acme\nlogo: logo.svg\n", {"logo.svg": b"<svg/>"})
        monkeypatch.chdir(tmp_path)
        brand = load_branding("branding.yaml")
        assert brand.source == (tmp_path / "branding.yaml").resolve()
        monkeypatch.chdir("/")
        assert brand.asset_path("logo.svg") == (tmp_path / "logo.svg").resolve()

    def test_every_validation_error_is_reported_at_once(self, tmp_path: Path) -> None:
        text = "version: 1\nname: ''\ncolors:\n  primary: red\nlogo: ../x.svg\nsurprise: 1\n"
        with pytest.raises(BrandingInvalidError) as excinfo:
            load_branding(_kit(tmp_path, text))
        errors = excinfo.value.extras["errors"]
        joined = "\n".join(errors)
        assert len(errors) == 4, errors
        for location in ("name", "colors.primary", "logo", "surprise"):
            assert location in joined

    def test_every_missing_asset_is_reported_at_once(self, tmp_path: Path) -> None:
        text = "version: 1\nname: Acme\nlogo: logo.svg\nfavicon: favicon.ico\ninvoice:\n  logo: inv.png\n"
        with pytest.raises(BrandingInvalidError) as excinfo:
            load_branding(_kit(tmp_path, text))
        errors = excinfo.value.extras["errors"]
        assert len(errors) == 3
        assert {"logo.svg", "favicon.ico", "inv.png"} == {e.rsplit(": ", 1)[1] for e in errors}

    def test_settings_path_is_the_default(self, custom_branding: Callable[..., Path]) -> None:
        custom_branding(name="From Settings")
        assert get_branding().name == "From Settings"
        assert load_branding().name == "From Settings"

    def test_get_branding_is_cached_per_process(self, custom_branding: Callable[..., Path]) -> None:
        path = custom_branding(name="First")
        first = get_branding()
        path.write_text(path.read_text().replace("First", "Second"))
        assert get_branding() is first  # restart (or reset_branding) to apply


class TestAssetPath:
    def test_refuses_unreferenced_names(self, tmp_path: Path) -> None:
        brand = load_branding(
            _kit(tmp_path, "version: 1\nname: Acme\nlogo: logo.svg\n", {"logo.svg": b"<svg/>", "x.svg": b"x"})
        )
        assert brand.asset_path("logo.svg") == (tmp_path / "logo.svg").resolve()
        for name in ("x.svg", "branding.yaml", "../branding.yaml", ".."):
            with pytest.raises(NotFoundError):
                brand.asset_path(name)

    def test_symlink_escaping_the_kit_is_refused(self, tmp_path: Path) -> None:
        outside = tmp_path / "secret.svg"
        outside.write_bytes(b"secret")
        kit = tmp_path / "kit"
        kit.mkdir()
        (kit / "logo.svg").symlink_to(outside)
        with pytest.raises(BrandingInvalidError, match=r"logo\.svg"):
            load_branding(_kit(kit, "version: 1\nname: Acme\nlogo: logo.svg\n"))


class TestStarterKit:
    def test_writes_the_packaged_kit_and_it_validates(self, tmp_path: Path) -> None:
        written = write_starter_kit(tmp_path / "kit")
        assert sorted(p.name for p in written) == ["branding.yaml", "favicon.svg", "logo.svg"]
        assert load_branding(tmp_path / "kit" / "branding.yaml").name == "Synapse"

    def test_refuses_to_overwrite_without_force(self, tmp_path: Path) -> None:
        write_starter_kit(tmp_path)
        (tmp_path / "branding.yaml").write_text("edited")
        with pytest.raises(FileExistsError):
            write_starter_kit(tmp_path)
        assert (tmp_path / "branding.yaml").read_text() == "edited"
        write_starter_kit(tmp_path, force=True)
        assert (tmp_path / "branding.yaml").read_text() != "edited"


class TestMediaTypes:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("a.svg", "image/svg+xml"),
            ("a.PNG", "image/png"),
            ("a.ico", "image/x-icon"),
            ("a.css", "text/css"),
            ("a.bin", "application/octet-stream"),
        ],
    )
    def test_by_extension(self, name: str, expected: str) -> None:
        assert asset_media_type(name) == expected


class TestPackagedKit:
    def test_repo_kit_and_packaged_default_are_identical(self) -> None:
        """config/branding/ (what you edit) == the copy shipped inside the wheel, file for file."""
        import importlib.resources

        packaged = importlib.resources.files("synapse_saas") / "config" / "branding"
        packaged_names = sorted(p.name for p in packaged.iterdir() if p.is_file())
        repo_names = sorted(p.name for p in REPO_KIT.iterdir() if p.is_file())
        assert packaged_names == repo_names == ["branding.yaml", "favicon.svg", "logo.svg"]
        for name in repo_names:
            assert (REPO_KIT / name).read_bytes() == (packaged / name).read_bytes(), (
                f"config/branding/{name} and src/synapse_saas/config/branding/{name} differ — "
                "copy the edited one over the other"
            )

    def test_compose_kit_is_a_copy_of_the_default(self) -> None:
        """deploy/compose/branding/ is what `docker compose up` mounts: the default kit, byte for byte."""
        names = sorted(p.name for p in COMPOSE_KIT.iterdir() if p.is_file())
        assert names == ["branding.yaml", "favicon.svg", "logo.svg"]
        for name in names:
            assert (COMPOSE_KIT / name).read_bytes() == (REPO_KIT / name).read_bytes(), (
                f"deploy/compose/branding/{name} differs from config/branding/{name} — copy it over"
            )

    def test_scaffold_kit_is_the_default_with_a_templated_name(self) -> None:
        names = sorted(p.name for p in SCAFFOLD_KIT.iterdir() if p.is_file())
        assert names == ["branding.yaml.tmpl", "favicon.svg", "logo.svg"]
        for name in ("favicon.svg", "logo.svg"):
            assert (SCAFFOLD_KIT / name).read_bytes() == (REPO_KIT / name).read_bytes(), name
        template = (SCAFFOLD_KIT / "branding.yaml.tmpl").read_text(encoding="utf-8")
        default = (REPO_KIT / "branding.yaml").read_text(encoding="utf-8")
        assert "\nname: $package_title\n" in template
        assert template.replace("\nname: $package_title\n", "\nname: Synapse\n") == default, (
            "the scaffold's branding.yaml.tmpl drifted from config/branding/branding.yaml"
        )

    def test_default_settings_point_at_the_packaged_kit(self) -> None:
        from synapse_saas.core.config import DEFAULT_BRANDING_FILE

        assert DEFAULT_BRANDING_FILE.name == "branding.yaml"
        assert "synapse_saas" in DEFAULT_BRANDING_FILE.parts
        assert DEFAULT_BRANDING_FILE.exists()

    def test_every_field_is_documented_in_the_starter_kit(self) -> None:
        """branding init hands this file to implementors: every schema key appears in it."""
        from synapse_saas.branding.models import BrandColors, BrandEmail, Branding, BrandInvoice, BrandLinks

        text = (REPO_KIT / "branding.yaml").read_text()
        for model in (Branding, BrandColors, BrandLinks, BrandEmail, BrandInvoice):
            for field in model.model_fields:
                assert f"{field}:" in text, f"{model.__name__}.{field} is undocumented in branding.yaml"
