import hashlib
import os
import re
import threading
import time
from collections import Counter, OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional
import httpx
from dotenv import load_dotenv

load_dotenv()

# Process-wide coordination for Qloo traffic. The semaphore is the single
# gatekeeper for live HTTP calls across every facade instance in this process.
_CACHE_LOCK = threading.Lock()
_CACHE_MAX_ENTRIES = 256
_NET_SEMAPHORE = threading.BoundedSemaphore(4)
_PROBE_LOCK = threading.Lock()
_SHARED_CACHE: Dict[str, "OrderedDict[str, Any]"] = {}
_SHARED_CAPABILITIES: Dict[str, Dict[str, bool]] = {}
_SHARED_PROBED: Dict[str, bool] = {}


def _default_capabilities() -> Dict[str, bool]:
    return {
        "explainability": False,
        "urn_demographics": False,
        "urn_heatmap": False,
        "urn_tag": False,
    }


# Tags that leak operational metadata instead of cultural vibe. Filtering these
# keeps the Vibe Lexicon useful for SEO/menu/event prompts.
_NOISE_TAG_FRAGMENTS = (
    "companies listed",
    "stock exchange",
    "credit card",
    "parking",
    "onsite",
    "on site",
    "bar seating",
    "top rated",
    "convenience",
    "event venue",
    "small plates",
)
_NOISE_TAGS = {"other", "dining", "fire", "alcohol", "evening", "sustainable living"}


def is_noise_tag(tag: str) -> bool:
    """Return True for operational metadata that is not a cultural signal."""
    t = (tag or "").strip().lower()
    if not t:
        return True
    if t in _NOISE_TAGS:
        return True
    if any(fragment in t for fragment in _NOISE_TAG_FRAGMENTS):
        return True
    if re.fullmatch(r"\d{2}\s+\d{2}", t):  # age bands such as "30 34"
        return True
    return False


class QlooFacade:
    """
    Minimal Facade over the Qloo v2 API for Alfred.
    Exposes the 8 core tools with built-in signal probing, tag harvesting,
    and progressive enhancement fallbacks.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("QLOO_API_KEY", "")
        self.base_url = (base_url or os.getenv("QLOO_BASE_URL", "https://hackathon.api.qloo.com")).rstrip("/")
        if not self.api_key:
            raise ValueError("Missing QLOO_API_KEY in environment or constructor.")

        self._cache_namespace = self._make_cache_namespace()
        self.client = httpx.Client(
            base_url=self.base_url,
            headers={"X-Api-Key": self.api_key, "Accept": "application/json"},
            timeout=20.0,
            limits=httpx.Limits(
                max_keepalive_connections=10,
                max_connections=10,
                keepalive_expiry=60.0,
            ),
        )
        with _CACHE_LOCK:
            self._cache = _SHARED_CACHE.setdefault(
                self._cache_namespace, OrderedDict()
            )
            self.capabilities = _SHARED_CAPABILITIES.setdefault(
                self._cache_namespace, _default_capabilities()
            )
        self._net_semaphore = _NET_SEMAPHORE

    def _make_cache_namespace(self) -> str:
        """Namespace shared state by endpoint and key without exposing the key."""
        digest = hashlib.sha256(self.api_key.encode("utf-8")).hexdigest()[:16]
        return f"{self.base_url}|{digest}"

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self.client.close()

    # -------------------------------------------------------------------------
    # Low-Level Transport + Defensive Wrapper
    # -------------------------------------------------------------------------
    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        clean_params = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        cache_key = f"{path}?{ sorted(clean_params.items()) }"

        # Double-checked cache: hits return before touching the network gate.
        with _CACHE_LOCK:
            if cache_key in self._cache:
                self._cache.move_to_end(cache_key)
                return self._cache[cache_key]

        for attempt in range(3):
            try:
                with self._net_semaphore:
                    resp = self.client.get(path, params=clean_params)
            except httpx.HTTPError as exc:
                # Transport-level failures (timeouts, resets) must never crash a tool.
                if attempt == 2:
                    return {"_error": "transport", "_detail": str(exc)[:300], "results": {}}
                time.sleep(0.6 * (attempt + 1))
                continue
            if resp.status_code == 429:
                time.sleep(0.6 * (attempt + 1))
                continue
            if resp.status_code >= 400:
                return {"_error": resp.status_code, "_detail": resp.text[:300], "results": {}}
            try:
                data = resp.json()
            except ValueError:
                return {"_error": "invalid_json", "_detail": resp.text[:300], "results": {}}

            with _CACHE_LOCK:
                self._cache[cache_key] = data
                self._cache.move_to_end(cache_key)
                while len(self._cache) > _CACHE_MAX_ENTRIES:
                    self._cache.popitem(last=False)
            return data
        return {"_error": 429, "results": {}}

    @staticmethod
    def _extract_entities(data: Dict[str, Any]) -> List[Dict[str, Any]]:
        results = data.get("results", data)
        if isinstance(results, dict):
            entities = results.get("entities", results.get("tags", []))
        elif isinstance(results, list):
            entities = results
        else:
            return []

        # Qloo can return the same entity more than once in a ranked list.
        # Dedupe by entity ID and by normalized (name, subtype) so dual entries
        # like the two "High Maintenance" series do not repeat in the same list.
        seen_ids = set()
        seen_names = set()
        unique = []
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            entity_id = entity.get("entity_id") or entity.get("id")
            name = (entity.get("name") or "").strip().lower()
            subtype = (entity.get("subtype") or entity.get("type") or "").strip().lower()
            if entity_id and entity_id in seen_ids:
                continue
            if name and (name, subtype) in seen_names:
                continue
            if entity_id:
                seen_ids.add(entity_id)
            if name:
                seen_names.add((name, subtype))
            unique.append(entity)
        return unique

    @staticmethod
    def _simplify_entity(e: Dict[str, Any]) -> Dict[str, Any]:
        props = e.get("properties", {}) or {}
        loc = e.get("location", {}) or props.get("location", {}) or {}
        tags = [
            t.get("name") or t.get("id")
            for t in (e.get("tags") or [])
            if isinstance(t, dict)
        ]
        return {
            "entity_id": e.get("entity_id") or e.get("id"),
            "name": e.get("name"),
            "subtype": e.get("subtype") or e.get("type"),
            "affinity": e.get("query", {}).get("affinity") or e.get("affinity"),
            "popularity": e.get("popularity"),
            "address": props.get("address"),
            "lat": loc.get("lat") or loc.get("latitude"),
            "lon": loc.get("lon") or loc.get("longitude"),
            "tags": tags[:10],
            "explainability": e.get("query", {}).get("explainability") or e.get("explainability"),
        }

    def search_places(self, query: str, take: int = 8) -> List[Dict[str, Any]]:
        """Search Qloo places while preserving category metadata for ranking.

        `/search` accepts a `types` filter but can still return parks, landmarks,
        and other non-restaurant places. The agent uses `category_tags` to pick a
        restaurant-like candidate instead of blindly taking the first result.
        """
        params: Dict[str, Any] = {
            "query": query,
            "types": "urn:entity:place",
            "take": max(take, 3),
        }
        data = self._get("/search", params)
        raw_entities = self._extract_entities(data)

        # Some keys ignore or reject the types filter. Retry once without it
        # rather than treating a valid query as a hard failure.
        if not raw_entities:
            data = self._get("/search", {"query": query, "take": max(take, 3)})
            raw_entities = self._extract_entities(data)

        candidates: List[Dict[str, Any]] = []
        for entity in raw_entities:
            types = entity.get("types") or []
            if types and "urn:entity:place" not in types:
                continue

            raw_tags = entity.get("tags") or []
            category_tags: List[str] = []
            for tag in raw_tags:
                if not isinstance(tag, dict):
                    continue
                tag_type = str(tag.get("type") or "")
                tag_value = tag.get("value") or tag.get("tag_id") or tag.get("id") or ""
                if tag_type.startswith("urn:tag:category:place") or str(tag_value).startswith(
                    "urn:tag:category:place"
                ):
                    category_tags.append(str(tag_value))

            props = entity.get("properties", {}) or {}
            simplified = self._simplify_entity(entity)
            simplified["types"] = types
            simplified["category_tags"] = category_tags
            simplified["website"] = props.get("website") or props.get("url")
            candidates.append(simplified)

        return candidates

    # -------------------------------------------------------------------------
    # Step 0: Progressive Enhancement Capability Probe
    # -------------------------------------------------------------------------
    def probe_optional_features(self, sample_entity_id: str) -> Dict[str, bool]:
        """Tests the 4 disputed endpoints/flags against the live key and records support."""
        namespace = self._cache_namespace
        with _PROBE_LOCK:
            with _CACHE_LOCK:
                if _SHARED_PROBED.get(namespace):
                    return self.capabilities

            checks = {
                "explainability": (
                    "/v2/insights",
                    {
                        "filter.type": "urn:entity:artist",
                        "signal.interests.entities": sample_entity_id,
                        "feature.explainability": "true",
                        "take": 2,
                    },
                ),
                "urn_demographics": (
                    "/v2/insights",
                    {
                        "filter.type": "urn:demographics",
                        "signal.interests.entities": sample_entity_id,
                    },
                ),
                "urn_heatmap": (
                    "/v2/insights",
                    {
                        "filter.type": "urn:heatmap",
                        "signal.interests.entities": sample_entity_id,
                        "filter.location.query": "Brooklyn",
                    },
                ),
                "urn_tag": (
                    "/v2/insights",
                    {
                        "filter.type": "urn:tag",
                        "filter.tag.types": "urn:tag:genre:music",
                        "signal.interests.entities": sample_entity_id,
                        "take": 5,
                    },
                ),
            }

            def run_check(item: Any) -> Any:
                key, (path, params) = item
                try:
                    return key, self._get(path, params)
                except Exception as exc:
                    return key, {
                        "_error": "exception",
                        "_detail": str(exc)[:300],
                        "results": {},
                    }

            with ThreadPoolExecutor(max_workers=4, thread_name_prefix="qloo-probe") as pool:
                results = list(pool.map(run_check, checks.items()))

            transient = False
            for key, data in results:
                error = data.get("_error")
                if error in (429, "transport", "invalid_json", "exception"):
                    transient = True
                if key == "explainability":
                    self.capabilities[key] = "_error" not in data
                else:
                    self.capabilities[key] = "_error" not in data and bool(data.get("results"))

            # A transient failure should not disable optional features for the
            # whole process lifetime. The next run can retry the probe.
            if not transient:
                with _CACHE_LOCK:
                    _SHARED_PROBED[namespace] = True
        return self.capabilities

    # -------------------------------------------------------------------------
    # TOOL 1: resolve_cultural_seeds
    # -------------------------------------------------------------------------
    def resolve_cultural_seeds(
        self,
        restaurant_name: str,
        vibe_seeds: List[str],
        tag_queries: List[str],
    ) -> Dict[str, Any]:
        """
        Resolves restaurant + owner vibe seeds into validated Qloo entity IDs and Tag URNs.
        Automatically probes each seed so weak/unusable signals are filtered out early.
        """
        queries = list(dict.fromkeys([restaurant_name] + list(vibe_seeds or [])))

        def resolve_one(query: str) -> Optional[Dict[str, Any]]:
            try:
                data = self._get("/search", {"query": query, "take": 3})
                candidates = self._extract_entities(data)
                if not candidates:
                    return None

                top = candidates[0]
                eid = top.get("entity_id") or top.get("id")
                if not eid:
                    return None

                # Probe if this entity works as a valid signal in /v2/insights
                probe = self._get("/v2/insights", {
                    "filter.type": "urn:entity:artist",
                    "signal.interests.entities": eid,
                    "take": 1,
                })
                usable = "_error" not in probe and len(self._extract_entities(probe)) > 0

                simp = self._simplify_entity(top)
                simp["query_term"] = query
                simp["usable_as_signal"] = usable
                return simp
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="qloo-seeds") as pool:
            resolved_seeds = [item for item in pool.map(resolve_one, queries) if item]

        harvested_tags: List[str] = []
        for seed in resolved_seeds:
            harvested_tags.extend(seed["tags"])

        # Resolve explicit tag queries via /v2/tags
        def resolve_tag(tag_query: str) -> Optional[Dict[str, Any]]:
            try:
                tdata = self._get("/v2/tags", {"query": tag_query, "take": 3})
                tlist = self._extract_entities(tdata)
                if not tlist:
                    return None
                turn = tlist[0].get("id") or tlist[0].get("tag_id")
                if not turn:
                    return None
                return {
                    "query": tag_query,
                    "tag_urn": turn,
                    "name": tlist[0].get("name"),
                }
            except Exception:
                return None

        if tag_queries:
            with ThreadPoolExecutor(max_workers=4, thread_name_prefix="qloo-tags") as pool:
                resolved_tag_urns = [
                    item for item in pool.map(resolve_tag, tag_queries) if item
                ]
        else:
            resolved_tag_urns = []

        valid_signal_ids = [s["entity_id"] for s in resolved_seeds if s["usable_as_signal"]]

        return {
            "resolved_entities": resolved_seeds,
            "valid_signal_entity_ids": valid_signal_ids,
            "resolved_tag_urns": resolved_tag_urns,
            "initial_harvested_tags": [t for t, _ in Counter(harvested_tags).most_common(15)],
        }

    # -------------------------------------------------------------------------
    # TOOL 2: compute_taste_dna
    # -------------------------------------------------------------------------
    def compute_taste_dna(
        self,
        signal_entity_ids: List[str],
        signal_tag_urns: Optional[List[str]] = None,
        domains: Optional[List[str]] = None,
        take: int = 8,
    ) -> Dict[str, Any]:
        """
        Cross-domain Cultural X-Ray across artist, brand, movie, tv_show, podcast, place.
        Harvests tags from all returned entities to build a zero-risk Vibe Lexicon.
        """
        domains = domains or ["artist", "brand", "movie", "tv_show", "podcast"]
        entities_param = ",".join(signal_entity_ids[:8])
        tags_param = ",".join(signal_tag_urns[:5]) if signal_tag_urns else None

        def fetch_domain(dom: str) -> Any:
            params: Dict[str, Any] = {
                "filter.type": f"urn:entity:{dom}",
                "signal.interests.entities": entities_param,
                "signal.interests.tags": tags_param,
                "take": take,
            }
            if self.capabilities.get("explainability"):
                params["feature.explainability"] = "true"
            try:
                res = self._get("/v2/insights", params)
                return dom, [self._simplify_entity(e) for e in self._extract_entities(res)]
            except Exception:
                return dom, []

        with ThreadPoolExecutor(max_workers=5, thread_name_prefix="qloo-dna") as pool:
            domain_results = list(pool.map(fetch_domain, domains))

        cross_domain: Dict[str, List[Dict[str, Any]]] = {}
        lexicon_counter: Counter = Counter()
        lexicon_display: Dict[str, str] = {}

        for dom, items in domain_results:
            cross_domain[dom] = items

            for item in items:
                for tag in item.get("tags", []):
                    if is_noise_tag(tag):
                        continue
                    key = tag.strip().lower()
                    lexicon_display.setdefault(key, tag.strip())
                    lexicon_counter[key] += 1

        return {
            "cross_domain_affinities": cross_domain,
            "vibe_lexicon": [lexicon_display[k] for k, _ in lexicon_counter.most_common(12)],
        }

    # -------------------------------------------------------------------------
    # TOOL 3: get_audience_signals
    # -------------------------------------------------------------------------
    def get_audience_signals(self, signal_entity_ids: List[str]) -> Dict[str, Any]:
        """
        Builds 3 grounded buyer personas using demographic signals on core entity calls
        (Low Risk) + optional standalone urn:demographics enhancement if supported.
        """
        entities_param = ",".join(signal_entity_ids[:5])
        buckets = ["25_to_29", "30_to_34", "35_to_44"]

        # Primary Safe Path: probe each age bucket concurrently.
        def fetch_bucket(bucket: str) -> Dict[str, Any]:
            try:
                res = self._get("/v2/insights", {
                    "filter.type": "urn:entity:brand",
                    "signal.interests.entities": entities_param,
                    "signal.demographics.age": bucket,
                    "take": 4,
                })
                top_brands = [self._simplify_entity(e)["name"] for e in self._extract_entities(res)]
            except Exception:
                top_brands = []
            return {
                "age_bucket": bucket,
                "top_indexing_brands": top_brands,
            }

        # Optional Enhancement: standalone urn:demographics
        def fetch_demographics() -> Any:
            try:
                d_res = self._get("/v2/insights", {
                    "filter.type": "urn:demographics",
                    "signal.interests.entities": entities_param,
                })
                return d_res.get("results")
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="qloo-audience") as pool:
            bucket_futures = [pool.submit(fetch_bucket, bucket) for bucket in buckets]
            demographics_future = (
                pool.submit(fetch_demographics)
                if self.capabilities.get("urn_demographics")
                else None
            )
            persona_slices = [future.result() for future in bucket_futures]
            raw_demographics = (
                demographics_future.result() if demographics_future else None
            )

        return {
            "persona_age_slices": persona_slices,
            "enhanced_demographics": raw_demographics,
        }

    # -------------------------------------------------------------------------
    # TOOL 4: find_affinity_places (Local Dining Peers & Map Pin Layer)
    # -------------------------------------------------------------------------
    def find_affinity_places(
        self,
        signal_entity_ids: List[str],
        lat: float,
        lon: float,
        radius_meters: int = 4000,
        take: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Finds nearby dining peers/competitors that share taste overlap.
        Also provides guaranteed lat/lon pins for the Neighborhood Taste Map.
        """
        res = self._get("/v2/insights", {
            "filter.type": "urn:entity:place",
            "filter.tags": "urn:tag:genre:place:restaurant",
            "filter.location": f"POINT({lon} {lat})",
            "filter.location.radius": radius_meters,
            "signal.interests.entities": ",".join(signal_entity_ids[:6]),
            "take": take,
        })
        return [self._simplify_entity(e) for e in self._extract_entities(res)]

    # -------------------------------------------------------------------------
    # TOOL 5: scout_local_partners (Non-Competing Local Collab Shortlist)
    # -------------------------------------------------------------------------
    def scout_local_partners(
        self,
        signal_entity_ids: List[str],
        lat: float,
        lon: float,
        radius_meters: int = 5000,
        max_popularity: float = 0.88,
        take: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Finds independent local venues (bars, coffee shops, record stores, boutiques,
        cultural spaces) within radius for Pillar D Co-Marketing Drops.
        """
        res = self._get("/v2/insights", {
            "filter.type": "urn:entity:place",
            "filter.location": f"POINT({lon} {lat})",
            "filter.location.radius": radius_meters,
            "filter.popularity.max": max_popularity,
            "signal.interests.entities": ",".join(signal_entity_ids[:6]),
            "take": take,
        })
        all_places = [self._simplify_entity(e) for e in self._extract_entities(res)]

        # Post-filter out direct full-service Italian/pizza competitors
        collab_partners = []
        for p in all_places:
            tags_lower = " ".join(p.get("tags", [])).lower()
            if "italian restaurant" in tags_lower or "pizzeria" in tags_lower:
                continue
            collab_partners.append(p)

        return collab_partners[:8]

    # -------------------------------------------------------------------------
    # TOOL 5b: get_local_heatmap (Geospatial affinity tiles)
    # -------------------------------------------------------------------------
    def get_local_heatmap(
        self,
        signal_entity_ids: List[str],
        location_query: str = "Brooklyn",
        take: int = 8,
    ) -> List[Dict[str, Any]]:
        """Fetches top geospatial affinity tiles via urn:heatmap if supported.

        The API ignores `take` and always returns the full tile grid (~875 tiles),
        so the limiting happens client-side.
        """
        if not self.capabilities.get("urn_heatmap") or not signal_entity_ids:
            return []
        res = self._get("/v2/insights", {
            "filter.type": "urn:heatmap",
            "signal.interests.entities": ",".join(signal_entity_ids[:5]),
            "filter.location.query": location_query,
        })
        results = res.get("results", {})
        tiles = results.get("heatmap", []) if isinstance(results, dict) else []
        simplified = []
        for t in tiles[:take]:
            loc = t.get("location", {}) or {}
            query = t.get("query", {}) or {}
            simplified.append({
                "lat": loc.get("latitude") or loc.get("lat"),
                "lon": loc.get("longitude") or loc.get("lon"),
                "affinity": query.get("affinity") or t.get("affinity"),
                "popularity": query.get("popularity") or t.get("popularity"),
            })
        return simplified

    # -------------------------------------------------------------------------
    # TOOL 6: compare_taste_overlap
    # -------------------------------------------------------------------------
    def compare_taste_overlap(
        self,
        signal_entity_ids_a: List[str],
        entity_id_b: str,
        tags_a: Optional[List[str]] = None,
        tags_b: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Head-to-head comparison between the restaurant's Taste DNA and a target
        partner or competitor via /v2/analysis/compare, with Jaccard tag fallback.
        """
        res = self._get("/v2/analysis/compare", {
            "a.signal.interests.entities": ",".join(signal_entity_ids_a[:5]),
            "b.signal.interests.entities": entity_id_b,
        })

        if "_error" not in res and res.get("results"):
            return {"method": "qloo_analysis_compare", "data": res.get("results")}

        # Fallback: Deterministic Jaccard overlap on entity tags
        set_a = set(t.lower() for t in (tags_a or []))
        set_b = set(t.lower() for t in (tags_b or []))
        shared = sorted(list(set_a & set_b))
        union = set_a | set_b
        jaccard = round(len(shared) / len(union), 3) if union else 0.0

        return {
            "method": "tag_jaccard_fallback",
            "jaccard_score": jaccard,
            "shared_tags": shared,
            "unique_to_restaurant": sorted(list(set_a - set_b))[:8],
        }

    # -------------------------------------------------------------------------
    # TOOL 7: score_candidates (Deterministic Scoring for the Focus Group)
    # -------------------------------------------------------------------------
    def score_candidates(
        self,
        candidate_entity_ids: List[str],
        persona_signal_ids: List[str],
        entity_type: str = "place",
        persona_age_bucket: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Powers the Multi-Agent Focus Group: deterministically scores & ranks a list
        of candidate entities against a specific Persona's signals + age demographic.
        """
        if not candidate_entity_ids:
            return []

        params: Dict[str, Any] = {
            "filter.type": f"urn:entity:{entity_type}",
            "filter.results.entities": ",".join(candidate_entity_ids[:15]),
            "signal.interests.entities": ",".join(persona_signal_ids[:6]),
            "take": len(candidate_entity_ids),
        }
        if persona_age_bucket:
            params["signal.demographics.age"] = persona_age_bucket

        res = self._get("/v2/insights", params)
        ranked = [self._simplify_entity(e) for e in self._extract_entities(res)]
        return ranked
