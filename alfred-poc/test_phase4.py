"""Offline Phase 4 regression tests.

These tests never call Qloo or an LLM. They cover shared cache state, the
process-wide network gate, one-time capability probing, parallel fan-out,
concurrent final stages, and the deterministic cliche scrubber.
"""

from __future__ import annotations

import json
import os
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import Mock, patch

from alfred_agent import AlfredAgent
from qloo_facade import QlooFacade

ROOT = Path(__file__).resolve().parent.parent


class FakeResponse:
    def __init__(self, payload: Dict[str, Any], status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self) -> Dict[str, Any]:
        return self._payload


class CountingClient:
    """Thread-safe fake HTTP client that records concurrency."""

    def __init__(self, payload: Optional[Dict[str, Any]] = None, delay: float = 0.0):
        self.payload = payload or {"results": {}}
        self.delay = delay
        self.calls: List[Any] = []
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> FakeResponse:
        with self.lock:
            self.calls.append((path, dict(params or {})))
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        if self.delay:
            time.sleep(self.delay)
        with self.lock:
            self.active -= 1
        return FakeResponse(self.payload)


def make_facade(label: str) -> QlooFacade:
    facade = QlooFacade(
        api_key="phase4-test-key",
        base_url=f"https://{label}.test",
    )
    # The real client is never used in these tests. Close it before swapping
    # in a fake so the suite does not leak connection pools.
    facade.client.close()
    return facade


def make_agent(facade: Any) -> AlfredAgent:
    with patch.dict(os.environ, {"LLM_API_KEY": "phase4-test-key"}, clear=False):
        with patch("alfred_agent.OpenAI"):
            return AlfredAgent(facade=facade, model="phase4-test-model")


def unique_label(test_name: str) -> str:
    return f"{test_name}-{uuid.uuid4().hex}"


class FacadeConcurrencyTests(unittest.TestCase):
    def test_shared_cache_and_capabilities_across_instances(self):
        label = unique_label("shared")
        first = make_facade(label)
        second = make_facade(label)
        first.client = CountingClient({"results": {"entities": [{"entity_id": "e1"}]}})
        second.client = CountingClient({"results": {"entities": [{"entity_id": "e1"}]}})

        first_result = first._get("/v2/insights", {"take": 1})
        second_result = second._get("/v2/insights", {"take": 1})

        self.assertEqual(first_result, second_result)
        self.assertEqual(len(first.client.calls), 1)
        self.assertEqual(len(second.client.calls), 0)
        self.assertIs(first._cache, second._cache)
        self.assertIs(first.capabilities, second.capabilities)

    def test_cache_hit_returns_before_network_gate(self):
        facade = make_facade(unique_label("cache-gate"))
        facade.client = CountingClient({"results": {}})
        facade._get("/v2/insights", {"take": 1})

        for _ in range(4):
            facade._net_semaphore.acquire()
        result: List[Any] = []
        thread = threading.Thread(
            target=lambda: result.append(facade._get("/v2/insights", {"take": 1})),
            daemon=True,
        )
        try:
            thread.start()
            thread.join(timeout=1.0)
            self.assertFalse(thread.is_alive(), "cache hit blocked on the network gate")
            self.assertEqual(len(facade.client.calls), 1)
            self.assertEqual(result, [{"results": {}}])
        finally:
            for _ in range(4):
                facade._net_semaphore.release()
            thread.join(timeout=1.0)

    def test_network_gate_caps_in_flight_requests_at_four(self):
        facade = make_facade(unique_label("gate"))
        client = CountingClient({"results": {}}, delay=0.05)
        facade.client = client

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda index: facade._get("/v2/insights", {"take": index}), range(8)))

        self.assertEqual(len(client.calls), 8)
        self.assertLessEqual(client.max_active, 4)
        self.assertGreater(client.max_active, 1)
        for _ in range(4):
            self.assertTrue(facade._net_semaphore.acquire(blocking=False))
        for _ in range(4):
            facade._net_semaphore.release()

    def test_client_uses_keepalive_connection_limits(self):
        with patch("qloo_facade.httpx.Client") as client_cls:
            QlooFacade(
                api_key="phase4-test-key",
                base_url=f"https://{unique_label('keepalive')}.test",
            )
            kwargs = client_cls.call_args.kwargs
        limits = kwargs["limits"]
        self.assertEqual(limits.max_connections, 10)
        self.assertEqual(limits.max_keepalive_connections, 10)
        self.assertEqual(kwargs["timeout"], 20.0)

    def test_capability_probe_runs_once_per_boot(self):
        label = unique_label("probe-once")
        first = make_facade(label)
        second = make_facade(label)
        calls = [0]
        lock = threading.Lock()

        def counting_get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
            with lock:
                calls[0] += 1
            return {"results": [{"entity_id": "probe-entity"}]}

        first._get = counting_get  # type: ignore[method-assign]
        second._get = counting_get  # type: ignore[method-assign]

        first_caps = first.probe_optional_features("signal-1")
        second_caps = second.probe_optional_features("signal-1")

        self.assertEqual(calls[0], 4)
        self.assertEqual(first_caps, second_caps)
        self.assertTrue(all(first_caps.values()))

    def test_transient_probe_failure_is_retried_on_next_run(self):
        facade = make_facade(unique_label("probe-retry"))
        calls = [0]
        lock = threading.Lock()

        def failing_get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
            with lock:
                calls[0] += 1
            return {"_error": 429, "results": {}}

        facade._get = failing_get  # type: ignore[method-assign]

        first_caps = dict(facade.probe_optional_features("signal-1"))
        second_caps = dict(facade.probe_optional_features("signal-1"))

        self.assertEqual(calls[0], 8)
        self.assertEqual(first_caps, second_caps)
        self.assertFalse(any(first_caps.values()))

    def test_taste_dna_preserves_domain_order_after_fan_out(self):
        facade = make_facade(unique_label("dna-order"))

        def fake_get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
            domain = str((params or {}).get("filter.type", "")).split(":")[-1]
            if domain == "artist":
                time.sleep(0.02)
            return {
                "results": {
                    "entities": [
                        {
                            "entity_id": f"{domain}-1",
                            "name": domain,
                            "tags": [{"name": f"{domain} tag"}],
                        }
                    ]
                }
            }

        facade._get = fake_get  # type: ignore[method-assign]
        domains = ["artist", "brand", "movie", "tv_show", "podcast"]
        dna = facade.compute_taste_dna(["signal-1"], domains=domains)

        self.assertEqual(list(dna["cross_domain_affinities"]), domains)


class AgentConcurrencyTests(unittest.TestCase):
    def test_stage_one_reads_run_concurrently(self):
        barrier = threading.Barrier(5)

        class StageOneFacade:
            def resolve_cultural_seeds(self, **kwargs: Any) -> Dict[str, Any]:
                return {
                    "valid_signal_entity_ids": ["signal-1"],
                    "resolved_tag_urns": [{"tag_urn": "urn:tag:test"}],
                    "resolved_entities": [],
                }

            def probe_optional_features(self, entity_id: str) -> Dict[str, bool]:
                return {
                    "explainability": False,
                    "urn_demographics": False,
                    "urn_heatmap": False,
                    "urn_tag": False,
                }

            def compute_taste_dna(self, **kwargs: Any) -> Dict[str, Any]:
                barrier.wait(timeout=2.0)
                return {
                    "cross_domain_affinities": {
                        "artist": [
                            {
                                "entity_id": "artist-1",
                                "name": "Artist",
                                "affinity": 0.9,
                                "tags": [],
                            }
                        ]
                    },
                    "vibe_lexicon": ["Tag"],
                }

            def get_audience_signals(self, **kwargs: Any) -> Dict[str, Any]:
                barrier.wait(timeout=2.0)
                return {"persona_age_slices": []}

            def find_affinity_places(self, **kwargs: Any) -> List[Any]:
                barrier.wait(timeout=2.0)
                return []

            def scout_local_partners(self, **kwargs: Any) -> List[Dict[str, Any]]:
                barrier.wait(timeout=2.0)
                return [
                    {
                        "entity_id": "partner-1",
                        "name": "Partner",
                        "tags": ["Tag"],
                        "address": "1 Test Street",
                        "affinity": 0.5,
                    }
                ]

            def get_local_heatmap(self, **kwargs: Any) -> List[Any]:
                barrier.wait(timeout=2.0)
                return []

            def compare_taste_overlap(self, **kwargs: Any) -> Dict[str, Any]:
                return {"method": "test_compare", "shared_tags": ["Tag"]}

        agent = make_agent(StageOneFacade())
        profile = {
            "name": "Test Restaurant",
            "vibe_seeds": ["Seed"],
            "tag_queries": ["Tag"],
            "lat": 40.0,
            "lon": -73.0,
            "neighborhood_city": "Brooklyn",
        }

        diagnosis = agent.ingest_and_diagnose(profile)

        self.assertEqual(diagnosis["signal_ids"], ["signal-1"])
        self.assertEqual(diagnosis["partner_comparisons"][0]["comparison_method"], "test_compare")

    def test_persona_scoring_runs_three_pairs_concurrently(self):
        barrier = threading.Barrier(3)

        class PersonaFacade:
            def __init__(self) -> None:
                self.calls: List[Dict[str, Any]] = []
                self.lock = threading.Lock()

            def score_candidates(self, **kwargs: Any) -> List[Dict[str, Any]]:
                with self.lock:
                    self.calls.append(kwargs)
                barrier.wait(timeout=2.0)
                return [
                    {
                        "name": f"{kwargs['entity_type']}-{kwargs['persona_age_bucket']}",
                        "affinity": 0.5,
                        "tags": [],
                    }
                ]

        facade = PersonaFacade()
        agent = make_agent(facade)
        diagnosis = {
            "signal_ids": ["signal-1"],
            "partner_candidates": [{"entity_id": "partner-1", "name": "Partner"}],
            "taste_dna": {
                "cross_domain_affinities": {
                    "artist": [{"entity_id": "artist-1", "name": "Artist"}]
                }
            },
            "audience_signals": {
                "persona_age_slices": [
                    {"age_bucket": "25_to_29", "top_indexing_brands": []},
                    {"age_bucket": "30_to_34", "top_indexing_brands": []},
                    {"age_bucket": "35_to_44", "top_indexing_brands": []},
                ]
            },
        }

        result = agent.materialize_personas(diagnosis)

        self.assertEqual(len(result), 3)
        self.assertEqual([item["age_bucket"] for item in result], ["25_to_29", "30_to_34", "35_to_44"])
        self.assertEqual(len(facade.calls), 6)

    def test_full_pipeline_runs_final_stages_concurrently(self):
        barrier = threading.Barrier(2)

        class FinalAgent(AlfredAgent):
            def ingest_and_diagnose(self, profile: Dict[str, Any]) -> Dict[str, Any]:
                return {"profile": profile}

            def materialize_personas(self, diagnosis: Dict[str, Any]) -> List[Any]:
                return []

            def run_focus_group(
                self,
                diagnosis: Dict[str, Any],
                persona_math_scores: Optional[List[Dict[str, Any]]] = None,
            ) -> Dict[str, Any]:
                return {"focus_group_debate": []}

            def generate_execution_pack(
                self,
                diagnosis: Dict[str, Any],
                focus_group: Dict[str, Any],
            ) -> Dict[str, Any]:
                barrier.wait(timeout=2.0)
                return {"pack": True}

            def generate_gut_vs_graph_control(
                self,
                diagnosis: Dict[str, Any],
                focus_group: Dict[str, Any],
            ) -> Dict[str, Any]:
                barrier.wait(timeout=2.0)
                return {"control": True}

        with patch.dict(os.environ, {"LLM_API_KEY": "phase4-test-key"}, clear=False):
            with patch("alfred_agent.OpenAI"):
                agent = FinalAgent(facade=object(), model="phase4-test-model")

        result = agent.run_full_pipeline({"name": "Test"})

        self.assertEqual(result["execution_pack"], {"pack": True})
        self.assertEqual(result["gut_vs_graph"], {"control": True})


class QualityRegressionTests(unittest.TestCase):
    def test_scrubber_protects_grounded_and_contrast_fields(self):
        pack = {
            "headline": (
                "Authentic cozy hidden gems with family traditions and Brooklyn vibes. "
                "Experience the vibe."
            ),
            "pillar_1_cultural_seo": {
                "before_generic_h1": "Authentic cozy hidden gem",
                "after_qloo_grounded_h1": "Cozy hidden gem",
                "qloo_tags_used": ["authentic", "cozy", "hidden gem"],
                "vibe_lexicon": ["authentic", "cozy"],
            },
            "pillar_2_menu_and_aov_engineering": {
                "menu_reframes": [
                    {
                        "original_item": "Cozy authentic pasta",
                        "upgraded_name_and_copy": "Cozy authentic pasta",
                    }
                ]
            },
            "pillar_3_anti_spam_sms_and_email": {
                "campaigns": [
                    {
                        "generic_llm_spam_version": "Cozy authentic hidden gem",
                        "alfred_qloo_grounded_sms": "Cozy authentic hidden gem",
                        "qloo_receipts_cited": ["authentic", "cozy"],
                    }
                ]
            },
            "pillar_4_local_collab_and_dead_night": {
                "selected_local_partner": {"name": "The Cozy Authentic Bar"},
                "dead_night_activation": {
                    "vibe_playlist_artists": ["Cozy Authentic"],
                    "instagram_caption": "A cozy hidden gem with family tradition.",
                },
            },
            "focus_group_results": {
                "initial_generic_draft": "Cozy authentic hidden gem",
                "blind_llm_without_qloo": "Cozy authentic hidden gem",
            },
        }

        scrubbed = AlfredAgent._scrub_banned_cliches(pack)

        headline = scrubbed["headline"].lower()
        for term in (
            "authentic",
            "cozy",
            "hidden gem",
            "taste of italy",
            "family tradition",
            "brooklyn vibe",
            "experience the vibe",
        ):
            self.assertNotIn(term, headline)
        self.assertIn("rooted", headline)
        self.assertIn("warm", headline)
        self.assertIn("neighborhood finds", headline)
        self.assertIn("house traditions", headline)
        self.assertIn("brooklyn energy", headline)
        self.assertIn("take in the atmosphere", headline)

        self.assertEqual(
            scrubbed["pillar_1_cultural_seo"]["before_generic_h1"],
            "Authentic cozy hidden gem",
        )
        self.assertEqual(
            scrubbed["pillar_1_cultural_seo"]["qloo_tags_used"],
            ["authentic", "cozy", "hidden gem"],
        )
        self.assertEqual(
            scrubbed["pillar_1_cultural_seo"]["vibe_lexicon"],
            ["authentic", "cozy"],
        )
        self.assertEqual(
            scrubbed["pillar_2_menu_and_aov_engineering"]["menu_reframes"][0]["original_item"],
            "Cozy authentic pasta",
        )
        self.assertNotIn(
            "cozy",
            scrubbed["pillar_2_menu_and_aov_engineering"]["menu_reframes"][0][
                "upgraded_name_and_copy"
            ].lower(),
        )
        self.assertEqual(
            scrubbed["pillar_3_anti_spam_sms_and_email"]["campaigns"][0][
                "generic_llm_spam_version"
            ],
            "Cozy authentic hidden gem",
        )
        self.assertNotIn(
            "cozy",
            scrubbed["pillar_3_anti_spam_sms_and_email"]["campaigns"][0][
                "alfred_qloo_grounded_sms"
            ].lower(),
        )
        self.assertEqual(
            scrubbed["pillar_3_anti_spam_sms_and_email"]["campaigns"][0][
                "qloo_receipts_cited"
            ],
            ["authentic", "cozy"],
        )
        self.assertEqual(
            scrubbed["pillar_4_local_collab_and_dead_night"]["selected_local_partner"]["name"],
            "The Cozy Authentic Bar",
        )
        self.assertEqual(
            scrubbed["pillar_4_local_collab_and_dead_night"]["dead_night_activation"][
                "vibe_playlist_artists"
            ],
            ["Cozy Authentic"],
        )
        self.assertNotIn(
            "cozy",
            scrubbed["pillar_4_local_collab_and_dead_night"]["dead_night_activation"][
                "instagram_caption"
            ].lower(),
        )
        self.assertEqual(
            scrubbed["focus_group_results"]["initial_generic_draft"],
            "Cozy authentic hidden gem",
        )
        self.assertEqual(
            scrubbed["focus_group_results"]["blind_llm_without_qloo"],
            "Cozy authentic hidden gem",
        )

    def test_execution_pack_does_not_retry_for_banned_terms(self):
        diagnosis = {
            "restaurant_profile": {"name": "Test", "menu_highlights": ["A", "B", "C"]},
            "taste_dna": {"vibe_lexicon": ["Tag"], "cross_domain_affinities": {}},
            "dining_peers": [],
            "partner_candidates": [],
            "partner_comparisons": [],
        }
        pack = self._complete_pack(headline="A cozy authentic hidden gem")
        agent = make_agent(object())
        agent._ask_json = Mock(return_value=pack)

        result = agent.generate_execution_pack(diagnosis, {"focus_group_debate": []})

        self.assertEqual(agent._ask_json.call_count, 1)
        self.assertNotIn(
            "cozy",
            result["pillar_1_cultural_seo"]["after_qloo_grounded_h1"].lower(),
        )

    def test_execution_pack_retries_only_for_incomplete_arrays(self):
        diagnosis = {
            "restaurant_profile": {"name": "Test", "menu_highlights": ["A", "B", "C"]},
            "taste_dna": {"vibe_lexicon": ["Tag"], "cross_domain_affinities": {}},
            "dining_peers": [],
            "partner_candidates": [],
            "partner_comparisons": [],
        }
        agent = make_agent(object())
        agent._ask_json = Mock(
            side_effect=[
                {"pillar_1_cultural_seo": {"ai_search_occasion_prompts": []}},
                self._complete_pack(headline="Grounded headline"),
            ]
        )

        result = agent.generate_execution_pack(diagnosis, {"focus_group_debate": []})

        self.assertEqual(agent._ask_json.call_count, 2)
        self.assertEqual(
            result["pillar_1_cultural_seo"]["after_qloo_grounded_h1"],
            "Grounded headline",
        )

    @staticmethod
    def _complete_pack(headline: str) -> Dict[str, Any]:
        return {
            "cultural_diagnosis_summary": {},
            "pillar_1_cultural_seo": {
                "ai_search_occasion_prompts": ["a", "b", "c"],
                "qloo_tags_used": ["Tag"],
                "after_qloo_grounded_h1": headline,
            },
            "pillar_2_menu_and_aov_engineering": {
                "menu_reframes": [
                    {"original_item": f"item-{index}", "upgraded_name_and_copy": headline}
                    for index in range(3)
                ],
                "direct_ordering_upsell_bundles": [{} for _ in range(3)],
                "b2b_catering_pitch": {},
            },
            "pillar_3_anti_spam_sms_and_email": {
                "campaigns": [
                    {
                        "generic_llm_spam_version": "cozy authentic",
                        "alfred_qloo_grounded_sms": headline,
                        "qloo_receipts_cited": ["Tag"],
                    }
                    for _ in range(3)
                ]
            },
            "pillar_4_local_collab_and_dead_night": {"selected_local_partner": {}},
        }


class DeploymentArtifactTests(unittest.TestCase):
    def test_license_files(self):
        for path in (ROOT / "LICENSE", ROOT / "alfred-poc" / "LICENSE"):
            text = path.read_text(encoding="utf-8")
            self.assertIn("MIT License", text)
            self.assertIn("2026 Shubham Kumar", text)

    def test_render_and_procfile_use_one_worker_and_keepalive(self):
        render = (ROOT / "render.yaml").read_text(encoding="utf-8")
        self.assertIn("runtime: python", render)
        self.assertIn("--workers 1", render)
        self.assertIn("--timeout-keep-alive 75", render)
        self.assertIn("0.0.0.0", render)
        self.assertIn("$PORT", render)

        procfile = (ROOT / "Procfile").read_text(encoding="utf-8")
        self.assertIn("${PORT:-8000}", procfile)
        self.assertIn("--workers 1", procfile)
        self.assertIn("--timeout-keep-alive 75", procfile)

        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("-r alfred-poc/requirements.txt", requirements)


if __name__ == "__main__":
    unittest.main(verbosity=2)
