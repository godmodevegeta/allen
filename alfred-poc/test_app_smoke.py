"""Offline smoke tests for the Alfred FastAPI server and SSE pipeline.

These tests never call Qloo or an LLM. They replace ``AlfredAgent`` with a
deterministic fake and exercise the same worker, finalization, SSE, and lock
paths used by the live dashboard.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as app_module

UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


def parse_sse(lines):
    """Convert SSE lines into a list of (event, payload) tuples."""
    current = None
    events = []
    for line in lines:
        if line.startswith("event: "):
            current = line[7:]
        elif line.startswith("data: "):
            events.append((current, json.loads(line[6:])))
    return events


class FakeAgent:
    """Small agent stand-in that preserves the app's stage contract."""

    instances = []
    fail_at = None
    execution_delay = 0.0
    gut_delay = 0.0

    def __init__(self, model=None):
        self.facade = None
        self.llm = None
        self.model = model
        self.bootstrap_args = None
        FakeAgent.instances.append(self)

    def bootstrap_custom_profile(
        self,
        name,
        city,
        primary_goal="",
        vibe_seeds_list=None,
        menu_highlights=None,
    ):
        self.bootstrap_args = {
            "name": name,
            "city": city,
            "primary_goal": primary_goal,
            "vibe_seeds_list": vibe_seeds_list,
            "menu_highlights": menu_highlights,
        }
        return {
            "name": name,
            "address": f"1 Test Street, {city}",
            "neighborhood_city": city,
            "lat": 40.0,
            "lon": -73.0,
            "primary_goal": primary_goal,
            "vibe_seeds": vibe_seeds_list or ["Test Seed"],
            "menu_highlights": menu_highlights or ["Test Dish"],
            "tag_queries": ["test"],
            "profile_source": "custom_qloo_search",
            "location_source": "qloo_search",
            "bootstrap_warning": "Test bootstrap warning.",
        }

    def ingest_and_diagnose(self, profile):
        if self.fail_at == "ingest":
            raise RuntimeError("synthetic failure")
        return {
            "restaurant_profile": profile,
            "seeds": {
                "resolved_entities": [
                    {
                        "query_term": "Test Seed",
                        "name": "Test Seed",
                        "affinity": 0.91,
                        "tags": ["Test"],
                        "usable_as_signal": True,
                    }
                ],
                "initial_harvested_tags": ["Test"],
            },
            "taste_dna": {"cross_domain_affinities": {}, "vibe_lexicon": ["Test"]},
            "audience_signals": {"persona_age_slices": []},
            "dining_peers": [],
            "partner_candidates": [],
            "partner_comparisons": [],
            "heatmap_hotspots": [],
        }

    def materialize_personas(self, diagnosis):
        if self.fail_at == "personas":
            raise RuntimeError("synthetic failure")
        return [
            {
                "age_bucket": "25_to_29",
                "top_brands": ["Test Brand"],
                "qloo_ranked_partners": [],
                "qloo_ranked_artists": [],
            }
        ]

    def run_focus_group(self, diagnosis, persona_math):
        return {
            "personas": [
                {
                    "persona_name": "Test Persona",
                    "age_bucket": "25_to_29",
                    "cultural_identity": "Test identity",
                }
            ],
            "focus_group_debate": [
                {
                    "campaign_type": "Test Campaign",
                    "initial_generic_draft": "Generic draft",
                    "winning_qloo_grounded_concept": "Grounded draft",
                    "persona_critiques": [
                        {
                            "persona_name": "Test Persona",
                            "authenticity_score_out_of_100": 30,
                            "critique": "Test critique",
                        }
                    ],
                }
            ],
            "persona_math_receipts": persona_math,
        }

    def generate_execution_pack(self, diagnosis, focus_group):
        time.sleep(self.execution_delay)
        if self.fail_at == "execution":
            raise RuntimeError("synthetic failure")
        assert focus_group
        return {
            "cultural_diagnosis_summary": {
                "headline_identity": "Test headline",
                "competitive_whitespace": "Test whitespace",
                "expected_kpi_impact": {},
            },
            "pillar_1_cultural_seo": {},
            "pillar_2_menu_and_aov_engineering": {},
            "pillar_3_anti_spam_sms_and_email": {"campaigns": []},
            "pillar_4_local_collab_and_dead_night": {},
        }

    def generate_gut_vs_graph_control(self, diagnosis, focus_group):
        time.sleep(self.gut_delay)
        if self.fail_at == "gut":
            raise RuntimeError("synthetic failure")
        assert focus_group
        return {"control_note": "Test control", "comparisons": []}


class AppSmokeTests(unittest.TestCase):
    def setUp(self):
        FakeAgent.instances = []
        FakeAgent.fail_at = None
        FakeAgent.execution_delay = 0.0
        FakeAgent.gut_delay = 0.0
        self.client = TestClient(app_module.app)

    def tearDown(self):
        deadline = time.time() + 2.0
        while app_module.LIVE_LOCK.locked() and time.time() < deadline:
            time.sleep(0.01)
        if app_module.LIVE_LOCK.locked():
            app_module.LIVE_LOCK.release()

    def stream(self, path):
        with self.client.stream("GET", path) as response:
            self.assertEqual(response.status_code, 200)
            return parse_sse(list(response.iter_lines()))

    def test_health(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertIn("preset_source", payload)
        self.assertIn("live_busy", payload)
        self.assertIn("live_model", payload)
        alias = self.client.get("/health")
        self.assertEqual(alias.status_code, 200)
        self.assertTrue(alias.json()["ok"])

    def test_index(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        html = response.text
        self.assertIn("Cultural X-Ray", html)
        self.assertIn("EventSource", html)
        self.assertIn("GTM Execution Hub", html)
        self.assertIn("live_model", html)
        self.assertNotIn("owner" + ".com", html.lower())
        self.assertNotIn("\u2014", html)

    def test_live_model_resolution(self):
        with patch.dict(
            os.environ,
            {"LIVE_LLM_MODEL": "", "LLM_MODEL": "preset-model"},
            clear=False,
        ):
            self.assertEqual(app_module._live_model(), "preset-model")
        with patch.dict(
            os.environ,
            {"LIVE_LLM_MODEL": "live-model", "LLM_MODEL": "preset-model"},
            clear=False,
        ):
            self.assertEqual(app_module._live_model(), "live-model")
            with patch.object(app_module, "AlfredAgent", FakeAgent):
                self.stream("/api/stream?preset=bonafini")
        self.assertEqual(FakeAgent.instances[0].model, "live-model")

    def test_preset_headers_and_shape(self):
        response = self.client.get("/api/preset/bonafini")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("x-alfred-preset"), "sanitized")
        self.assertIn("max-age=60", response.headers.get("cache-control", ""))
        data = response.json()
        self.assertEqual(
            set(data),
            {"diagnosis", "persona_math", "focus_group", "execution_pack", "gut_vs_graph", "_meta"},
        )
        self.assertEqual(len(data["diagnosis"]["seeds"]["resolved_entities"]), 5)
        self.assertEqual(len(data["focus_group"]["personas"]), 3)
        self.assertEqual(len(data["focus_group"]["focus_group_debate"]), 3)
        self.assertEqual(len(data["gut_vs_graph"]["comparisons"]), 3)
        self.assertEqual(len(data["execution_pack"]["pillar_3_anti_spam_sms_and_email"]["campaigns"]), 3)
        for seed in data["diagnosis"]["seeds"]["resolved_entities"]:
            self.assertIn("usable_as_signal", seed)
        for comparison in data["diagnosis"]["partner_comparisons"]:
            self.assertIn("comparison_method", comparison)
            self.assertIn("partner_affinity", comparison)
            self.assertIn("partner_tags", comparison)

    def test_preset_is_sanitized(self):
        data = self.client.get("/api/preset/bonafini").json()
        serialized = json.dumps(data)
        self.assertNotRegex(serialized, UUID_RE)
        self.assertNotIn("signal_ids", serialized)
        self.assertNotIn("comparison_summary", serialized)
        self.assertNotIn("enhanced_demographics", serialized)
        self.assertNotIn("\u2014", serialized)

    def test_live_stream_stage_order(self):
        with patch.object(app_module, "AlfredAgent", FakeAgent):
            events = self.stream("/api/stream?preset=bonafini")
        names = [name for name, _ in events]
        self.assertEqual(
            names[:8],
            [
                "status",
                "diagnosis",
                "status",
                "persona_math",
                "status",
                "focus_group",
                "status",
                "status",
            ],
        )
        self.assertEqual(set(names[8:10]), {"execution_pack", "gut_vs_graph"})
        self.assertEqual(names[-1], "done")
        self.assertEqual(len(names), 11)
        stages = [payload["stage"] for name, payload in events if name == "status"]
        self.assertEqual(stages, [1, 2, 3, 4, 5])
        self.assertTrue(all(event != "error" for event in names))
        self.assertFalse(app_module.LIVE_LOCK.locked())
        self.assertEqual(len(FakeAgent.instances), 1)

    def test_live_stream_emits_first_completed_stage(self):
        FakeAgent.execution_delay = 0.3
        FakeAgent.gut_delay = 0.0
        with patch.object(app_module, "AlfredAgent", FakeAgent):
            events = self.stream("/api/stream?preset=bonafini")
        names = [name for name, _ in events]
        final_results = [name for name in names if name in {"execution_pack", "gut_vs_graph"}]
        self.assertEqual(final_results, ["gut_vs_graph", "execution_pack"])
        self.assertEqual(names[-1], "done")
        self.assertFalse(app_module.LIVE_LOCK.locked())

    def test_live_stream_final_stages_run_concurrently(self):
        barrier = threading.Barrier(2)

        class BarrierAgent(FakeAgent):
            def generate_execution_pack(self, diagnosis, focus_group):
                barrier.wait(timeout=2.0)
                return super().generate_execution_pack(diagnosis, focus_group)

            def generate_gut_vs_graph_control(self, diagnosis, focus_group):
                barrier.wait(timeout=2.0)
                return super().generate_gut_vs_graph_control(diagnosis, focus_group)

        with patch.object(app_module, "AlfredAgent", BarrierAgent):
            events = self.stream("/api/stream?preset=bonafini")
        names = [name for name, _ in events]
        self.assertIn("execution_pack", names)
        self.assertIn("gut_vs_graph", names)
        self.assertEqual(names[-1], "done")
        self.assertFalse(app_module.LIVE_LOCK.locked())

    def test_live_stream_custom_bootstrap(self):
        with patch.object(app_module, "AlfredAgent", FakeAgent):
            events = self.stream(
                "/api/stream?name=Lilia&city=Brooklyn&goal=Fill%20Tuesdays&seeds=Roberta%27s%2C%20A24"
            )
        names = [name for name, _ in events]
        self.assertIn("notice", names)
        self.assertIn("diagnosis", names)
        status = next(payload for name, payload in events if name == "status")
        self.assertEqual(status["stage"], 0)
        instance = FakeAgent.instances[0]
        self.assertEqual(instance.bootstrap_args["name"], "Lilia")
        self.assertEqual(instance.bootstrap_args["city"], "Brooklyn")
        self.assertEqual(instance.bootstrap_args["primary_goal"], "Fill Tuesdays")
        self.assertEqual(instance.bootstrap_args["vibe_seeds_list"], ["Roberta's", "A24"])
        self.assertFalse(app_module.LIVE_LOCK.locked())

    def test_live_stream_safe_error(self):
        class FailingAgent(FakeAgent):
            def __init__(self, model=None):
                super().__init__(model=model)
                self.fail_at = "execution"

        with patch.object(app_module, "AlfredAgent", FailingAgent):
            with self.assertLogs("alfred.app", level="ERROR"):
                events = self.stream("/api/stream?preset=bonafini")
        names = [name for name, _ in events]
        self.assertEqual(names[-1], "error")
        payload = events[-1][1]
        self.assertEqual(payload["stage"], 4)
        self.assertNotIn("synthetic failure", payload["message"])
        self.assertFalse(app_module.LIVE_LOCK.locked())

    def test_busy_lock_returns_safe_error(self):
        app_module.LIVE_LOCK.acquire()
        try:
            events = self.stream("/api/stream?preset=bonafini")
        finally:
            if app_module.LIVE_LOCK.locked():
                app_module.LIVE_LOCK.release()
        self.assertEqual(events[0][0], "error")
        self.assertEqual(events[0][1]["stage"], 0)
        self.assertTrue(events[0][1]["retryable"])
        self.assertIn("Another live run", events[0][1]["message"])

    def test_custom_validation(self):
        response = self.client.get("/api/stream?name=OnlyName")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Both restaurant name and city are required.")
        response = self.client.get("/api/stream?preset=nope")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Unknown preset.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
