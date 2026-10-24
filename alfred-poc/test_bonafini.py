import json
from qloo_facade import QlooFacade

# Test Profile: Bonafini Italian Restaurant (Prospect Lefferts Gardens, Brooklyn)
# Google Maps: https://maps.app.goo.gl/NP6vEYqKkGfNQ8Hc7
BONAFINI_PROFILE = {
    "name": "Bonafini",
    "address": "663 Flatbush Ave, Brooklyn, NY 11225",
    "lat": 40.6591,
    "lon": -73.9606,
    # Cultural North Star seeds representing cozy Brooklyn neighborhood pasta/pizza/martini bar
    "vibe_seeds": [
        "Roberta's",          # Iconic Brooklyn wood-fired pizza / neighborhood energy
        "Frankies 457",       # Cozy Brooklyn Italian staple
        "Khruangbin",         # Warm dinner/cocktail vinyl vibe
        "A24",                # Brooklyn indie film crowd
    ],
    "tag_queries": ["italian", "neapolitan pizza", "cocktails", "brunch"],
}


def run_bonafini_verification():
    facade = QlooFacade()
    print("=" * 72)
    print("ALFRED x QLOO FACADE VERIFICATION - BONAFINI ITALIAN RESTAURANT (BK)")
    print("=" * 72)

    # 1. Tool 1: Resolve Cultural Seeds + Signal Probing
    print("\n[1/8] Running resolve_cultural_seeds...")
    seeds = facade.resolve_cultural_seeds(
        restaurant_name=BONAFINI_PROFILE["name"],
        vibe_seeds=BONAFINI_PROFILE["vibe_seeds"],
        tag_queries=BONAFINI_PROFILE["tag_queries"],
    )
    signal_ids = seeds["valid_signal_entity_ids"]
    tag_urns = [t["tag_urn"] for t in seeds["resolved_tag_urns"]]
    print(f"  -> Resolved {len(seeds['resolved_entities'])} entities ({len(signal_ids)} usable as signals)")
    for s in seeds["resolved_entities"]:
        print(f"     • {s['query_term']} => {s['name']} ({s['entity_id']}) [Signal OK: {s['usable_as_signal']}]")
    assert len(signal_ids) > 0, "Expected at least 1 valid signal entity ID!"

    # Step 0: Probe optional enhancements with the first valid seed
    print("\n[0/8] Probing optional endpoint capabilities on this API key...")
    caps = facade.probe_optional_features(signal_ids[0])
    print(f"  -> Capabilities detected: {json.dumps(caps)}")

    # 2. Tool 2: Compute Taste DNA (Cross-Domain X-Ray + Vibe Lexicon)
    print("\n[2/8] Running compute_taste_dna...")
    dna = facade.compute_taste_dna(signal_entity_ids=signal_ids, signal_tag_urns=tag_urns, take=5)
    for dom, items in dna["cross_domain_affinities"].items():
        names = [f"{i['name']} ({round(i['affinity'] or 0, 2)})" for i in items[:4]]
        print(f"  -> Top {dom.upper()}: {', '.join(names)}")
    print(f"  -> Harvested Vibe Lexicon: {', '.join(dna['vibe_lexicon'][:10])}")

    # 3. Tool 3: Get Audience Signals (Persona Grounding)
    print("\n[3/8] Running get_audience_signals...")
    aud = facade.get_audience_signals(signal_entity_ids=signal_ids)
    for p in aud["persona_age_slices"]:
        print(f"  -> Persona [{p['age_bucket']}]: Top Brands = {', '.join(p['top_indexing_brands'])}")

    # 4. Tool 4: Find Affinity Places (Local Brooklyn Dining Peers & Map Pins)
    print("\n[4/8] Running find_affinity_places (4km around 663 Flatbush Ave)...")
    peers = facade.find_affinity_places(
        signal_entity_ids=signal_ids,
        lat=BONAFINI_PROFILE["lat"],
        lon=BONAFINI_PROFILE["lon"],
        radius_meters=4000,
        take=6,
    )
    for peer in peers[:5]:
        print(f"  -> Peer: {peer['name']} | Affinity: {peer['affinity']} | Coords: ({peer['lat']}, {peer['lon']})")

    # 5. Tool 5: Scout Local Partners (Non-Competing Brooklyn Collab Venues)
    print("\n[5/8] Running scout_local_partners (5km around 663 Flatbush Ave)...")
    partners = facade.scout_local_partners(
        signal_entity_ids=signal_ids,
        lat=BONAFINI_PROFILE["lat"],
        lon=BONAFINI_PROFILE["lon"],
        radius_meters=5000,
    )
    for pt in partners[:5]:
        print(f"  -> Partner Candidate: {pt['name']} | Tags: {', '.join(pt['tags'][:3])}")

    # 6. Tool 6: Compare Taste Overlap (Bonafini DNA vs Top Local Partner/Peer)
    print("\n[6/8] Running compare_taste_overlap...")
    target = (partners or peers)[0]
    comparison = facade.compare_taste_overlap(
        signal_entity_ids_a=signal_ids,
        entity_id_b=target["entity_id"],
        tags_a=dna["vibe_lexicon"],
        tags_b=target.get("tags", []),
    )
    print(f"  -> Compared against '{target['name']}' via [{comparison['method']}]")

    # 7. Tool 7: Score Candidates (Focus Group Deterministic Re-Ranking)
    print("\n[7/8] Running score_candidates (Simulating 2 Focus Group Personas scoring partners)...")
    candidate_ids = [p["entity_id"] for p in (partners or peers)[:5] if p.get("entity_id")]
    for age_bucket in ["25_to_29", "35_to_44"]:
        scored = facade.score_candidates(
            candidate_entity_ids=candidate_ids,
            persona_signal_ids=signal_ids,
            entity_type="place",
            persona_age_bucket=age_bucket,
        )
        ranked_str = ", ".join([f"{s['name']} ({round(s['affinity'] or 0, 3)})" for s in scored[:3]])
        print(f"  -> Persona [{age_bucket}] Ranked Top 3: {ranked_str}")

    print("\n[8/8] Running get_local_heatmap (Brooklyn affinity hotspots)...")
    hotspots = facade.get_local_heatmap(
        signal_entity_ids=signal_ids,
        location_query="Brooklyn",
        take=6,
    )
    if not hotspots:
        print("  -> urn:heatmap unsupported on this key; facade returned [] as designed.")
    else:
        for tile in hotspots:
            print(
                f"  -> Hotspot: ({tile['lat']}, {tile['lon']}) | "
                f"Affinity: {tile['affinity']} | Popularity: {tile['popularity']}"
            )

    print("\nALL 8 QLOO FACADE TOOLS VERIFIED SUCCESSFULLY!")


if __name__ == "__main__":
    run_bonafini_verification()
