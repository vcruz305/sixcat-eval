from __future__ import annotations

from sixcat.__main__ import main
from sixcat.policy import (
    family_from_source,
    resolve_policy,
    vendor_family_catalog,
)


def test_adopted_family_applies_glm_recipe_to_unmapped_model():
    with __import__("warnings").catch_warnings(record=True) as caught:
        __import__("warnings").simplefilter("always")
        fallback = resolve_policy("vendor", "acme-glm-next")
    assert fallback.name == "strict"
    assert any("unknown model" in str(item.message) for item in caught)

    adopted = resolve_policy("vendor", "acme-glm-next", family="glm-5.x")
    glm = resolve_policy("vendor", "z-ai/glm-5.3")
    assert adopted.name == "vendor"
    assert adopted.temperature == glm.temperature
    assert adopted.top_p == glm.top_p
    assert "adopted-for=acme-glm-next" in adopted.source
    assert family_from_source(adopted.source) == "glm-5.x"


def test_unknown_family_is_rejected():
    try:
        resolve_policy("vendor", "mystery-7b", family="not-a-family")
    except ValueError as exc:
        assert "unknown vendor family" in str(exc)
    else:
        raise AssertionError("expected unknown family to fail")


def test_catalog_suggests_glm_family_for_future_alias():
    catalog = vendor_family_catalog(model="acme-glm-next")
    assert catalog["mapping"] is None
    families = [item["family"] for item in catalog["suggested"]]
    assert "glm-5.x" in families


def test_cli_families_json_and_policy_family_guard():
    assert main(["families", "--model", "acme-glm-next", "--json"]) == 0
    try:
        main(["--model", "x", "--policy", "custom", "--temperature", "0.7", "--policy-family", "glm-5.x"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected --policy-family to require vendor/both")
