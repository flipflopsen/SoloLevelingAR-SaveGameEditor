"""Effective display-name resolution combining catalog data and user overrides.

Precedence (TASK.md section 4.3, "Effective display names"):

1. User-defined override (persisted, namespace-scoped).
2. Validated, namespace-scoped canonical game-data name.
3. Direct catalog match from the legacy merged lookup (kept as a lower-
   confidence fallback since it can collide across unrelated ID spaces).
4. Deterministic fallback: ``<namespace>:<raw-id>`` (or
   ``<namespace>:<context>:<raw-id>`` when context is part of identity).
"""

from __future__ import annotations

from .catalog import CatalogResolver
from .entity_overrides import EntityOverrideStore, MappingKey

# Maps each UI-facing entity namespace to the specific GameData source
# catalogs (by filename stem) that are confirmed or reasonably expected to
# contain its raw IDs. Keeping this mapping explicit (rather than resolving
# through one merged ID->name dict) is what makes namespace collisions safe:
# two different namespaces never share a name just because a raw ID matches.
NAMESPACE_SOURCE_FILES: dict[str, tuple[str, ...]] = {
    "hunter": ("ChHunt", "ChShad"),
    "item": ("It", "ItArti", "ItemGS", "ItRelic"),
    "owned_artifact": ("ItArti",),
    "owned_relic_weapon": ("ItRelic",),
    "owned_hunter_weapon": ("It", "ItemGS"),
    "owned_blessing_stone": ("ItArti", "It"),
    "cosmetic": ("CharCostume", "ItemEmoticon", "ItemProfile"),
    "title": ("ItemTitle",),
    "achievement": ("Achi",),
}


class NameResolver:
    """Resolve the effective display name for a namespaced entity identity."""

    def __init__(self, catalog: CatalogResolver, overrides: EntityOverrideStore) -> None:
        self._catalog = catalog
        self._overrides = overrides

    def resolve(self, namespace: str, raw_id: int, context: str | None = None) -> str:
        key = MappingKey(namespace, raw_id, context)
        override = self._overrides.get(key)
        if override:
            return override
        source_files = NAMESPACE_SOURCE_FILES.get(namespace, ())
        namespaced_name = self._catalog.name_in(source_files, raw_id)
        if namespaced_name:
            return namespaced_name
        return self._deterministic_fallback(namespace, raw_id, context)

    def set_override(self, namespace: str, raw_id: int, context: str | None, value: str) -> str:
        key = MappingKey(namespace, raw_id, context)
        self._overrides.set(key, value)
        return self.resolve(namespace, raw_id, context)

    @staticmethod
    def _deterministic_fallback(namespace: str, raw_id: int, context: str | None) -> str:
        if context is not None:
            return f"{namespace}:{context}:{raw_id}"
        return f"{namespace}:{raw_id}"
