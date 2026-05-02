"""S12-BAZAAR-03 — validation harness for CDP Bazaar discovery extensions.

For each entry in ``BAZAAR_EXTENSIONS``:

1. Pydantic shape validates (description >= 40 chars, tags list, schema dict).
2. ``schema.properties.input`` and ``schema.properties.output`` are present.
3. ``input`` example validates against ``schema.properties.input`` under
   strict JSON Schema rules. This catches the "rejected on first settle"
   case Bazaar surfaces async, before deploy.
4. Every key in ``BAZAAR_EXTENSIONS`` matches a real entry in the
   x402 routes config (no metadata for routes that don't exist).
5. ``/.well-known/x402`` surfaces the extension blob per route.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator

import jsonschema  # type: ignore[import-untyped]
import pytest
from fastapi.testclient import TestClient

# Force stub mode BEFORE importing the app — settings are frozen at import time.
os.environ.setdefault("X402_MODE", "stub")
os.environ.setdefault("GECKO_WALLET_ADDRESS", "STUB_WALLET_ADDRESS_NOT_FOR_LIVE")


@pytest.fixture
def client() -> Iterator[TestClient]:
    for mod in [m for m in sys.modules if m.startswith("gecko_api")]:
        sys.modules.pop(mod, None)
    from gecko_api.main import app

    with TestClient(app) as c:
        yield c


def test_every_extension_input_validates_against_schema() -> None:
    """The example input on each extension must validate against its schema.

    This is the exact check Bazaar's extension validator runs at settle
    time; failing it locally means the listing would be rejected.
    """
    from gecko_api.bazaar import BAZAAR_EXTENSIONS

    for route, ext in BAZAAR_EXTENSIONS.items():
        properties = ext.schema_.get("properties", {})
        input_schema = properties.get("input")
        assert input_schema is not None, f"{route}: schema.properties.input missing"
        output_schema = properties.get("output")
        assert output_schema is not None, f"{route}: schema.properties.output missing"

        try:
            jsonschema.validate(instance=ext.input, schema=input_schema)
        except jsonschema.ValidationError as exc:
            pytest.fail(f"{route}: input example failed schema validation: {exc.message}")


def test_every_extension_has_semantic_description() -> None:
    """Descriptions must be substantial (>= 40 chars) and not just the path."""
    from gecko_api.bazaar import BAZAAR_EXTENSIONS

    for route, ext in BAZAAR_EXTENSIONS.items():
        assert len(ext.description) >= 40, f"{route}: description too short for semantic search"
        assert route.split(" ", 1)[-1] not in ext.description, (
            f"{route}: description leaks the URL path; rewrite for semantic search"
        )


def test_every_extension_has_tags() -> None:
    """Tags drive Bazaar facet filters; require at least one."""
    from gecko_api.bazaar import BAZAAR_EXTENSIONS

    for route, ext in BAZAAR_EXTENSIONS.items():
        assert ext.tags, f"{route}: at least one tag required"
        for tag in ext.tags:
            assert tag.strip(), f"{route}: empty tag in {ext.tags}"


def test_extensions_match_registered_routes() -> None:
    """No extension may declare metadata for a route that isn't registered.

    Catches stale entries left behind after a route rename or removal.
    """
    from gecko_api.bazaar import BAZAAR_EXTENSIONS
    from gecko_api.main import _routes_config

    for route in BAZAAR_EXTENSIONS:
        assert route in _routes_config, (
            f"BAZAAR_EXTENSIONS has metadata for {route!r} but no x402 RouteConfig"
        )


def test_well_known_surfaces_extension_blobs(client: TestClient) -> None:
    """/.well-known/x402 must include bazaarExtension on each decorated route."""
    from gecko_api.bazaar import BAZAAR_EXTENSIONS

    res = client.get("/.well-known/x402")
    assert res.status_code == 200
    body = res.json()
    by_route = {entry["route"]: entry for entry in body["routes"]}

    for route in BAZAAR_EXTENSIONS:
        assert route in by_route, f"{route} missing from /.well-known/x402 catalog"
        ext = by_route[route].get("bazaarExtension")
        assert ext is not None, f"{route}: bazaarExtension blob missing"
        assert ext["description"], f"{route}: extension description empty"
        # Wire-shape check: the alias-renamed `schema_` field lands as `schema`.
        assert "schema" in ext, f"{route}: extension wire shape missing 'schema'"
        assert "schema_" not in ext, (
            f"{route}: serialization leaked the python field name 'schema_'"
        )


def test_required_routes_are_decorated() -> None:
    """The Sprint 12 Track B targets must all carry Bazaar metadata.

    Per `docs/build-plan-sprint-12.md`: at minimum POST /research, POST
    /research/pro, POST /plan are required. Adjust this list when
    Track B's scope changes.
    """
    from gecko_api.bazaar import BAZAAR_EXTENSIONS

    required = {"POST /research", "POST /research/pro", "POST /plan"}
    missing = required - set(BAZAAR_EXTENSIONS)
    assert not missing, f"Sprint 12 Track B requires Bazaar metadata for: {missing}"
