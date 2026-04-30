# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Tests for engramia.providers._ollama_native (Phase 6.6 #4).

Three areas:
- ``native_base_url`` URL normalisation between OpenAI-compat and native.
- ``OllamaModelCache`` TTL + invalidation behaviour.
- ``recommended_timeout`` mapping from parameter_size strings to seconds.

The HTTP-level helpers (``list_models``, ``show_model``, ``is_reachable``)
are exercised by the integration-style tests in test_validator_ollama.py
which mock httpx end-to-end. Here we test only the pure-Python plumbing.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from engramia.providers._ollama_native import (
    OllamaModel,
    OllamaModelCache,
    model_is_pulled,
    native_base_url,
    recommended_timeout,
)


class TestNativeBaseURL:
    @pytest.mark.parametrize(
        ("input_url", "expected"),
        [
            ("http://localhost:11434/v1", "http://localhost:11434"),
            ("http://localhost:11434/v1/", "http://localhost:11434"),
            ("http://localhost:11434", "http://localhost:11434"),
            ("http://localhost:11434/", "http://localhost:11434"),
            ("https://ollama.example.com:8080/v1", "https://ollama.example.com:8080"),
            # Trailing /v1 stripped exactly once — extra path segments preserved
            ("http://host:11434/proxy/v1", "http://host:11434/proxy"),
        ],
    )
    def test_strips_trailing_v1(self, input_url, expected):
        assert native_base_url(input_url) == expected

    def test_does_not_strip_v1_in_middle_of_path(self):
        # "/v1" in the middle of a path is part of someone's reverse proxy
        # — leave it alone.
        assert native_base_url("http://host/v1/something") == "http://host/v1/something"


class TestModelIsPulled:
    @pytest.fixture
    def pulled(self):
        return [
            OllamaModel(name="llama3.3:latest"),
            OllamaModel(name="qwen2.5:7b"),
            OllamaModel(name="nomic-embed-text:latest"),
        ]

    def test_exact_match(self, pulled):
        assert model_is_pulled(pulled, "qwen2.5:7b") is True

    def test_bare_name_matches_latest_tag(self, pulled):
        # Tenants typically save "llama3.3" — that should match "llama3.3:latest"
        assert model_is_pulled(pulled, "llama3.3") is True
        assert model_is_pulled(pulled, "nomic-embed-text") is True

    def test_missing_returns_false(self, pulled):
        assert model_is_pulled(pulled, "deepseek-r1") is False

    def test_empty_wanted_treated_as_no_constraint(self, pulled):
        # When credential.default_model is unset, validation skips the
        # pulled-model check.
        assert model_is_pulled(pulled, "") is True
        assert model_is_pulled([], "") is True

    def test_specific_tag_does_not_match_latest(self, pulled):
        # If the tenant pinned :7b, we don't accept :latest as a substitute
        # (different model). We only accept the bare-name → :latest sugar.
        assert model_is_pulled([OllamaModel(name="llama3.3:latest")], "llama3.3:8b") is False


class TestOllamaModelCache:
    def test_get_returns_none_for_unknown_server(self):
        cache = OllamaModelCache()
        assert cache.get("http://nowhere:11434") is None

    def test_put_then_get_round_trips(self):
        cache = OllamaModelCache()
        models = [OllamaModel(name="llama3.3:latest")]
        cache.put("http://localhost:11434", models)
        assert cache.get("http://localhost:11434") == models

    def test_put_with_v1_suffix_get_without(self):
        """Both URL forms hit the same cache key."""
        cache = OllamaModelCache()
        models = [OllamaModel(name="llama3.3:latest")]
        cache.put("http://localhost:11434/v1", models)
        # Same logical server, different surface — should be a hit.
        assert cache.get("http://localhost:11434") == models

    def test_ttl_expiry_drops_entry(self):
        cache = OllamaModelCache(ttl_s=0.05)
        cache.put("http://h:11434", [OllamaModel(name="x:latest")])
        time.sleep(0.1)
        assert cache.get("http://h:11434") is None

    def test_invalidate_drops_one_server(self):
        cache = OllamaModelCache()
        cache.put("http://a:11434", [OllamaModel(name="x:latest")])
        cache.put("http://b:11434", [OllamaModel(name="y:latest")])
        cache.invalidate("http://a:11434")
        assert cache.get("http://a:11434") is None
        assert cache.get("http://b:11434") is not None

    def test_clear_drops_everything(self):
        cache = OllamaModelCache()
        cache.put("http://a:11434", [OllamaModel(name="x:latest")])
        cache.put("http://b:11434", [OllamaModel(name="y:latest")])
        cache.clear()
        assert cache.get("http://a:11434") is None
        assert cache.get("http://b:11434") is None


class TestRecommendedTimeout:
    @pytest.mark.parametrize(
        ("param_size", "expected"),
        [
            ("0.5B", 60.0),
            ("1B", 60.0),
            ("7B", 120.0),
            ("13B", 180.0),
            ("70B", 600.0),
            ("405B", 1800.0),
        ],
    )
    def test_known_param_sizes(self, param_size, expected):
        assert recommended_timeout(param_size) == expected

    def test_unknown_param_size_falls_back_to_default(self):
        assert recommended_timeout("999B-custom") == 300.0

    def test_none_falls_back_to_default(self):
        assert recommended_timeout(None) == 300.0


class TestOllamaProviderListModels:
    """OllamaProvider.list_models() bridges the cache to the public API."""

    def test_first_call_hits_http_subsequent_use_cache(self):
        from engramia.providers._ollama_native import get_default_cache
        from engramia.providers.ollama import OllamaProvider

        get_default_cache().clear()  # isolate from other tests

        models = [OllamaModel(name="llama3.3:latest"), OllamaModel(name="qwen:7b")]
        with patch("engramia.providers.ollama.list_models", return_value=models) as mock_list:
            # Construct without auto-timeout (avoid /api/show call)
            provider = OllamaProvider(model="llama3.3", base_url="http://test:11434/v1", timeout=60.0)
            first = provider.list_models()
            second = provider.list_models()

        assert first == models
        assert second == models
        # HTTP only fetched once — second hit was the cache.
        assert mock_list.call_count == 1

    def test_force_refresh_bypasses_cache(self):
        from engramia.providers._ollama_native import get_default_cache
        from engramia.providers.ollama import OllamaProvider

        get_default_cache().clear()

        models_v1 = [OllamaModel(name="llama3.3:latest")]
        models_v2 = [OllamaModel(name="llama3.3:latest"), OllamaModel(name="qwen:7b")]
        with patch(
            "engramia.providers.ollama.list_models",
            side_effect=[models_v1, models_v2],
        ) as mock_list:
            provider = OllamaProvider(model="llama3.3", base_url="http://test:11434/v1", timeout=60.0)
            first = provider.list_models()
            second = provider.list_models(force_refresh=True)

        assert first == models_v1
        assert second == models_v2
        assert mock_list.call_count == 2
