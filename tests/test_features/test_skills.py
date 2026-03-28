# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""D10 — Skills subsystem.

Tests skill registration and tag-based pattern discovery:
  1. Single skill search → patterns with that skill.
  2. Multi-skill intersection (match_all=True) → only exact match.
  3. Multi-skill union (match_all=False) → any match.
  4. Unknown skill → empty result.
  5. Skill case-insensitivity.
"""
from __future__ import annotations

from tests.recall_quality.conftest import TestClient, learn_and_get_key
from tests.recall_quality.snippets import CLUSTER_SNIPPETS
from tests.recall_quality.task_clusters import CLUSTERS


def test_skills_single_tag_match(client: TestClient, run_tag: str) -> None:
    """find_by_skills(['csv']) returns patterns tagged with 'csv'."""
    learned_keys: list[str] = []
    try:
        snippet = CLUSTER_SNIPPETS["C01"]["good"]
        task = f"[{run_tag}] sk1 {CLUSTERS['C01'][0]}"
        key = learn_and_get_key(client, task=task, code=snippet["code"], eval_score=9.0)
        if key:
            learned_keys.append(key)
            client.register_skills(key, ["csv_parsing", "row_filter"])

        matches = client.find_by_skills(["csv_parsing"], match_all=True)
        keys_found = {m["pattern_key"] for m in matches}
        assert key in keys_found, (
            "Pattern with skill 'csv_parsing' not found in find_by_skills result"
        )
    finally:
        for k in set(learned_keys):
            client.delete_pattern(k)


def test_skills_multi_intersection(client: TestClient, run_tag: str) -> None:
    """match_all=True: only patterns with ALL required skills are returned."""
    learned_keys: list[str] = []
    try:
        s_a = CLUSTER_SNIPPETS["C01"]["good"]
        s_b = CLUSTER_SNIPPETS["C02"]["good"]

        key_a = learn_and_get_key(
            client,
            task=f"[{run_tag}] sk2a {CLUSTERS['C01'][1]}",
            code=s_a["code"],
            eval_score=9.0,
        )
        key_b = learn_and_get_key(
            client,
            task=f"[{run_tag}] sk2b {CLUSTERS['C02'][1]}",
            code=s_b["code"],
            eval_score=9.0,
        )
        for k in (key_a, key_b):
            if k:
                learned_keys.append(k)

        if key_a:
            client.register_skills(key_a, ["csv", "pandas"])
        if key_b:
            client.register_skills(key_b, ["csv", "aggregation"])

        # Both have "csv", only A has "pandas"
        matches_all = client.find_by_skills(["csv", "pandas"], match_all=True)
        found_keys = {m["pattern_key"] for m in matches_all}

        if key_a:
            assert key_a in found_keys, "Pattern with ['csv','pandas'] not in match_all result"
        if key_b:
            assert key_b not in found_keys, (
                "Pattern with ['csv','aggregation'] should NOT match ['csv','pandas'] with match_all=True"
            )

    finally:
        for k in set(learned_keys):
            client.delete_pattern(k)


def test_skills_multi_union(client: TestClient, run_tag: str) -> None:
    """match_all=False: patterns with ANY required skill are returned."""
    learned_keys: list[str] = []
    try:
        s_c = CLUSTER_SNIPPETS["C05"]["good"]
        s_d = CLUSTER_SNIPPETS["C09"]["good"]

        key_c = learn_and_get_key(
            client,
            task=f"[{run_tag}] sk3c {CLUSTERS['C05'][2]}",
            code=s_c["code"],
            eval_score=9.0,
        )
        key_d = learn_and_get_key(
            client,
            task=f"[{run_tag}] sk3d {CLUSTERS['C09'][2]}",
            code=s_d["code"],
            eval_score=9.0,
        )
        for k in (key_c, key_d):
            if k:
                learned_keys.append(k)

        if key_c:
            client.register_skills(key_c, ["http_retry"])
        if key_d:
            client.register_skills(key_d, ["async_http"])

        # Union: should find both
        matches_any = client.find_by_skills(["http_retry", "async_http"], match_all=False)
        found_keys = {m["pattern_key"] for m in matches_any}

        for k, label in ((key_c, "http_retry"), (key_d, "async_http")):
            if k:
                assert k in found_keys, (
                    f"Pattern with skill '{label}' not found with match_all=False"
                )

    finally:
        for k in set(learned_keys):
            client.delete_pattern(k)


def test_skills_unknown_skill_empty(client: TestClient, run_tag: str) -> None:
    """Searching for a skill that no pattern has returns empty list."""
    matches = client.find_by_skills(["nonexistent_skill_xyz_42"], match_all=True)
    assert matches == [], (
        f"Expected empty result for unknown skill, got {len(matches)} matches"
    )


def test_skills_case_insensitive(client: TestClient, run_tag: str) -> None:
    """Skill lookup is case-insensitive."""
    learned_keys: list[str] = []
    try:
        snippet = CLUSTER_SNIPPETS["C10"]["good"]
        task = f"[{run_tag}] sk5 {CLUSTERS['C10'][0]}"
        key = learn_and_get_key(client, task=task, code=snippet["code"], eval_score=9.0)
        if key:
            learned_keys.append(key)
            client.register_skills(key, ["Email_Parsing"])  # mixed case

        # Search with lowercase
        matches = client.find_by_skills(["email_parsing"], match_all=True)
        if key:
            found = any(m["pattern_key"] == key for m in matches)
            assert found, "Skill search should be case-insensitive"

    finally:
        for k in set(learned_keys):
            client.delete_pattern(k)
