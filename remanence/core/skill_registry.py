"""Skill registry for capability-based pattern discovery.

Complements semantic search with explicit skill tags.
Each pattern can declare skills (e.g. "csv_parsing", "api_fetch", "data_viz")
that are stored and searchable.

Skills are stored under the "skills/" namespace in the storage backend.
"""

import logging

from remanence.providers.base import StorageBackend

_log = logging.getLogger(__name__)

_SKILLS_KEY = "skills/_registry"


class SkillRegistry:
    """Registry of skills associated with stored patterns.

    Args:
        storage: Storage backend to persist the skill index.
    """

    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage

    def register(self, pattern_key: str, skills: list[str]) -> None:
        """Associate skills with a pattern.

        Args:
            pattern_key: Storage key of the pattern (e.g. "patterns/abc_123").
            skills: List of skill tags (e.g. ["csv_parsing", "statistics"]).
        """
        if not skills:
            return
        normalized = [s.lower().strip() for s in skills if s.strip()]
        registry = self._load()
        registry[pattern_key] = normalized
        self._storage.save(_SKILLS_KEY, registry)
        _log.info("Registered skills %s for %s", normalized, pattern_key)

    def unregister(self, pattern_key: str) -> None:
        """Remove skill associations for a pattern.

        Args:
            pattern_key: Storage key to unregister.
        """
        registry = self._load()
        if pattern_key in registry:
            del registry[pattern_key]
            self._storage.save(_SKILLS_KEY, registry)

    def find_by_skills(
        self,
        required: list[str],
        match_all: bool = True,
    ) -> list[str]:
        """Find pattern keys that have the required skills.

        Args:
            required: List of skill tags to search for.
            match_all: If True, pattern must have ALL required skills.
                If False, ANY matching skill is sufficient.

        Returns:
            List of pattern keys matching the criteria.
        """
        if not required:
            return []
        normalized = {s.lower().strip() for s in required}
        registry = self._load()
        results: list[str] = []

        for key, skills in registry.items():
            skill_set = set(skills)
            if match_all:
                if normalized.issubset(skill_set):
                    results.append(key)
            else:
                if normalized & skill_set:
                    results.append(key)

        return results

    def get_skills(self, pattern_key: str) -> list[str]:
        """Get skills for a specific pattern.

        Args:
            pattern_key: Storage key of the pattern.

        Returns:
            List of skill tags, or empty list if not registered.
        """
        registry = self._load()
        return registry.get(pattern_key, [])

    def list_all_skills(self) -> list[str]:
        """Return all unique skill tags across all patterns.

        Returns:
            Sorted list of unique skill names.
        """
        registry = self._load()
        all_skills: set[str] = set()
        for skills in registry.values():
            all_skills.update(skills)
        return sorted(all_skills)

    def _load(self) -> dict[str, list[str]]:
        data = self._storage.load(_SKILLS_KEY)
        if not isinstance(data, dict):
            return {}
        return data
