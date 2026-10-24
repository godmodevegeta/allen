"""Build the committed Bonafini preset from a verified agent run.

The source file is a full local Qloo + LLM run. This script strips raw entity IDs,
signal IDs, comparison dumps, and unused diagnostics before writing the preset the
web UI loads instantly.

Usage:
    python scripts/build_preset.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv  # noqa: E402
from alfred_agent import AlfredAgent  # noqa: E402
from qloo_facade import is_noise_tag  # noqa: E402

load_dotenv()

UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
PLACEHOLDER_RE = re.compile(r"\[[^\[\]]{2,}\]")
EM_DASH = "\u2014"

_EXTRA_TAG_NOISE = (
    "established in",
    "establishments in",
    "companies based",
    "film distributors",
    "production companies",
    "high chairs",
    "kids menu",
    "wheelchair",
    "accessible",
    "nfc",
    "paid street parking",
    "valet",
    "order ahead",
    "counter service",
    "dine in",
    "delivery",
    "takeout",
    "reservation",
    "cash only",
    "credit cards",
    "visa",
    "mastercard",
    "amex",
    "american express",
    "bar service",
)


def _strings(value: Iterable[Any], limit: int | None = None) -> List[str]:
    result: List[str] = []
    for item in value or []:
        if not isinstance(item, str):
            continue
        text = " ".join(item.split())
        if text:
            result.append(text)
        if limit is not None and len(result) >= limit:
            break
    return result


def _tags(value: Iterable[Any], limit: int) -> List[str]:
    result: List[str] = []
    for item in value or []:
        if not isinstance(item, str):
            continue
        text = " ".join(item.split())
        if not text or is_noise_tag(text):
            continue
        lowered = text.lower()
        if any(fragment in lowered for fragment in _EXTRA_TAG_NOISE):
            continue
        if len(text) > 56:
            continue
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _clean_seeds(seeds: Dict[str, Any]) -> Dict[str, Any]:
    resolved: List[Dict[str, Any]] = []
    for item in seeds.get("resolved_entities") or []:
        if not isinstance(item, dict):
            continue
        resolved.append(
            {
                "query_term": item.get("query_term"),
                "name": item.get("name"),
                "affinity": item.get("affinity"),
                "tags": _tags(item.get("tags") or [], 6),
                "usable_as_signal": bool(item.get("usable_as_signal")),
            }
        )
    return {
        "resolved_entities": resolved,
        "initial_harvested_tags": _tags(seeds.get("initial_harvested_tags") or [], 24),
    }


def _clean_taste_dna(taste_dna: Dict[str, Any]) -> Dict[str, Any]:
    cleaned: Dict[str, Any] = {"cross_domain_affinities": {}}
    for domain, items in (taste_dna.get("cross_domain_affinities") or {}).items():
        domain_items: List[Dict[str, Any]] = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            domain_items.append(
                {
                    "name": item.get("name"),
                    "affinity": item.get("affinity"),
                    "tags": _tags(item.get("tags") or [], 8),
                }
            )
        cleaned["cross_domain_affinities"][str(domain)] = domain_items
    cleaned["vibe_lexicon"] = _tags(taste_dna.get("vibe_lexicon") or [], 24)
    return cleaned


def _clean_audience(audience: Dict[str, Any]) -> Dict[str, Any]:
    slices: List[Dict[str, Any]] = []
    for item in audience.get("persona_age_slices") or []:
        if not isinstance(item, dict):
            continue
        slices.append(
            {
                "age_bucket": item.get("age_bucket"),
                "top_indexing_brands": _strings(item.get("top_indexing_brands") or [], 10),
            }
        )
    # enhanced_demographics is intentionally dropped. It is not needed by the UI
    # and adds raw Qloo detail that the committed preset should not carry.
    return {"persona_age_slices": slices}


def _clean_places(places: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    for item in places or []:
        if not isinstance(item, dict):
            continue
        cleaned.append(
            {
                "name": item.get("name"),
                "affinity": item.get("affinity"),
                "address": item.get("address"),
                "lat": item.get("lat"),
                "lon": item.get("lon"),
                "tags": _tags(item.get("tags") or [], 8),
            }
        )
    return cleaned


def _clean_comparisons(
    comparisons: Iterable[Dict[str, Any]],
    partner_affinities: Dict[str, Any],
) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    for item in comparisons or []:
        if not isinstance(item, dict):
            continue
        partner_name = item.get("partner_name")
        cleaned.append(
            {
                "partner_name": partner_name,
                "partner_tags": _tags(item.get("partner_tags") or [], 6),
                "partner_address": item.get("partner_address"),
                "partner_affinity": item.get("partner_affinity", partner_affinities.get(partner_name)),
                "comparison_method": item.get("comparison_method"),
            }
        )
    return cleaned


def _clean_heatmap(hotspots: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    for item in hotspots or []:
        if not isinstance(item, dict):
            continue
        cleaned.append(
            {
                "lat": item.get("lat"),
                "lon": item.get("lon"),
                "affinity": item.get("affinity"),
            }
        )
    return cleaned


def build_preset(raw: Dict[str, Any]) -> Dict[str, Any]:
    diagnosis = raw.get("diagnosis") or {}
    seeds = diagnosis.get("seeds") or {}
    partner_candidates = _clean_places(diagnosis.get("partner_candidates") or [])
    partner_affinities = {
        item.get("name"): item.get("affinity")
        for item in partner_candidates
        if item.get("name")
    }

    clean_diagnosis: Dict[str, Any] = {
        "restaurant_profile": diagnosis.get("restaurant_profile") or {},
        "seeds": _clean_seeds(seeds),
        "taste_dna": _clean_taste_dna(diagnosis.get("taste_dna") or {}),
        "audience_signals": _clean_audience(diagnosis.get("audience_signals") or {}),
        "dining_peers": _clean_places(diagnosis.get("dining_peers") or []),
        "partner_candidates": partner_candidates,
        "partner_comparisons": _clean_comparisons(
            diagnosis.get("partner_comparisons") or [],
            partner_affinities,
        ),
        "heatmap_hotspots": _clean_heatmap(diagnosis.get("heatmap_hotspots") or []),
    }

    preset: Dict[str, Any] = {
        "diagnosis": clean_diagnosis,
        "persona_math": raw.get("persona_math") or [],
        "focus_group": raw.get("focus_group") or {},
        "execution_pack": raw.get("execution_pack") or {},
        "gut_vs_graph": raw.get("gut_vs_graph") or {},
        "_meta": {
            "label": "Verified Bonafini snapshot",
            "generated_at": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "sanitized": True,
            "source": "Verified Qloo and LLM run, sanitized for display",
        },
    }
    model = os.getenv("LLM_MODEL")
    if model:
        preset["_meta"]["model"] = model
    return preset


def _walk_strings(value: Any, path: str = "$"):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_strings(item, f"{path}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_strings(item, f"{path}.{key}")


def validate_preset(preset: Dict[str, Any]) -> None:
    required = {"diagnosis", "persona_math", "focus_group", "execution_pack", "gut_vs_graph"}
    missing = sorted(required - set(preset))
    if missing:
        raise SystemExit(f"Preset is missing top-level stages: {missing}")

    seeds = preset["diagnosis"]["seeds"]["resolved_entities"]
    if not seeds:
        raise SystemExit("Preset has no resolved seed entities.")
    for index, seed in enumerate(seeds):
        if "usable_as_signal" not in seed:
            raise SystemExit(f"Seed {index} is missing usable_as_signal.")
        if "entity_id" in seed:
            raise SystemExit(f"Seed {index} still contains entity_id.")

    comparisons = preset["diagnosis"]["partner_comparisons"]
    for index, comparison in enumerate(comparisons):
        if "comparison_method" not in comparison:
            raise SystemExit(f"Comparison {index} is missing comparison_method.")
        if "comparison_summary" in comparison:
            raise SystemExit(f"Comparison {index} still contains comparison_summary.")

    if "enhanced_demographics" in preset["diagnosis"]["audience_signals"]:
        raise SystemExit("audience_signals still contains enhanced_demographics.")
    if "signal_ids" in preset["diagnosis"]:
        raise SystemExit("diagnosis still contains signal_ids.")

    problems: List[str] = []
    for path, text in _walk_strings(preset):
        if UUID_RE.search(text):
            problems.append(f"{path}: raw UUID")
        if EM_DASH in text:
            problems.append(f"{path}: em dash")
        if PLACEHOLDER_RE.search(text):
            problems.append(f"{path}: bracketed placeholder")
        if len(problems) >= 12:
            break
    if problems:
        raise SystemExit("Preset quality check failed:\n" + "\n".join(problems))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=BASE_DIR / "alfred_bonafini_output.json",
        help="Verified full agent output JSON.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=BASE_DIR / "presets" / "bonafini_preset.json",
        help="Destination for the sanitized preset.",
    )
    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(
            f"Missing source run: {args.input}. Run test_agent_bonafini.py first."
        )

    raw = json.loads(args.input.read_text(encoding="utf-8"))
    preset = build_preset(raw)
    preset = AlfredAgent.finalize_stage(preset)
    validate_preset(preset)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(preset, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    size_kb = args.output.stat().st_size / 1024
    print(f"Wrote {args.output} ({size_kb:.1f} KB)")
    print(
        "Seeds: "
        f"{len(preset['diagnosis']['seeds']['resolved_entities'])} | "
        f"Personas: {len(preset['persona_math'])} | "
        f"Debates: {len(preset['focus_group'].get('focus_group_debate') or [])} | "
        f"Comparisons: {len(preset['gut_vs_graph'].get('comparisons') or [])}"
    )


if __name__ == "__main__":
    main()
