# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for SkillRegistry."""

from engramia.core.skill_registry import SkillRegistry


class TestSkillRegistry:
    """Tests for the skill registry."""

    def test_register_and_get(self, storage):
        registry = SkillRegistry(storage)
        registry.register("patterns/abc_123", ["csv_parsing", "statistics"])

        skills = registry.get_skills("patterns/abc_123")
        assert "csv_parsing" in skills
        assert "statistics" in skills

    def test_register_normalizes_to_lowercase(self, storage):
        registry = SkillRegistry(storage)
        registry.register("patterns/abc_123", ["CSV_Parsing", "  Statistics  "])

        skills = registry.get_skills("patterns/abc_123")
        assert "csv_parsing" in skills
        assert "statistics" in skills

    def test_register_empty_skills_noop(self, storage):
        registry = SkillRegistry(storage)
        registry.register("patterns/abc_123", [])
        assert registry.get_skills("patterns/abc_123") == []

    def test_find_by_skills_match_all(self, storage):
        registry = SkillRegistry(storage)
        registry.register("patterns/a", ["csv", "statistics", "plotting"])
        registry.register("patterns/b", ["csv", "api"])
        registry.register("patterns/c", ["api", "plotting"])

        # Only patterns/a has both csv and statistics
        results = registry.find_by_skills(["csv", "statistics"], match_all=True)
        assert "patterns/a" in results
        assert "patterns/b" not in results

    def test_find_by_skills_match_any(self, storage):
        registry = SkillRegistry(storage)
        registry.register("patterns/a", ["csv", "statistics"])
        registry.register("patterns/b", ["api", "plotting"])
        registry.register("patterns/c", ["csv", "api"])

        # Any pattern with csv should match
        results = registry.find_by_skills(["csv"], match_all=False)
        assert "patterns/a" in results
        assert "patterns/c" in results
        assert "patterns/b" not in results

    def test_find_empty_required(self, storage):
        registry = SkillRegistry(storage)
        registry.register("patterns/a", ["csv"])
        assert registry.find_by_skills([]) == []

    def test_unregister(self, storage):
        registry = SkillRegistry(storage)
        registry.register("patterns/abc_123", ["csv"])
        registry.unregister("patterns/abc_123")
        assert registry.get_skills("patterns/abc_123") == []

    def test_list_all_skills(self, storage):
        registry = SkillRegistry(storage)
        registry.register("patterns/a", ["csv", "statistics"])
        registry.register("patterns/b", ["api", "csv"])

        all_skills = registry.list_all_skills()
        assert sorted(all_skills) == ["api", "csv", "statistics"]

    def test_get_skills_nonexistent_key(self, storage):
        registry = SkillRegistry(storage)
        assert registry.get_skills("patterns/nonexistent") == []

    def test_persistence(self, storage):
        registry1 = SkillRegistry(storage)
        registry1.register("patterns/a", ["csv", "statistics"])

        # Create a new registry instance with the same storage
        registry2 = SkillRegistry(storage)
        assert registry2.get_skills("patterns/a") == ["csv", "statistics"]
