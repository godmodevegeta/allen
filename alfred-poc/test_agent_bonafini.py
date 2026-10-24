import json
import re
from alfred_agent import AlfredAgent
from profiles import BONAFINI_FULL_PROFILE


def main():
    agent = AlfredAgent()
    result = agent.run_full_pipeline(BONAFINI_FULL_PROFILE)

    with open("alfred_bonafini_output.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    fg = result["focus_group"]
    pack = result["execution_pack"]
    gvg = result["gut_vs_graph"]

    print("\n" + "=" * 76)
    print("ALFRED MULTI-AGENT EXECUTION REPORT - BONAFINI (663 FLATBUSH AVE, BROOKLYN)")
    print("=" * 76)

    print("\n--- GROUNDED PERSONAS (WITH QLOO SCORE_CANDIDATES) ---")
    for p in fg.get("personas", []):
        print(
            f"* {p.get('persona_name', 'Unnamed persona')} [{p.get('age_bucket', '?')}]: "
            f"Partner={p.get('top_qloo_partner_pick')} | Artist={p.get('top_qloo_artist_pick')}"
        )
        print(f"  Identity: {p.get('cultural_identity')}")

    print("\n--- FOCUS GROUP DEBATE WINNER ---")
    for d in fg.get("focus_group_debate", []):
        print(f"* [{d.get('campaign_type')}]")
        print(f"  Rejected Generic Idea: {d.get('initial_generic_draft')}")
        print(f"  Approved Qloo Winner : {d.get('winning_qloo_grounded_concept')}")

    print("\n--- PILLAR 1: CULTURAL SEO ---")
    seo = pack.get("pillar_1_cultural_seo", {})
    print(f"  Before H1 : {seo.get('before_generic_h1')}")
    print(f"  After H1  : {seo.get('after_qloo_grounded_h1')}")

    print("\n--- PILLAR 2: DIRECT-ORDER AOV BUNDLES ---")
    for b in pack.get("pillar_2_menu_and_aov_engineering", {}).get("direct_ordering_upsell_bundles", []):
        print(
            f"  * {b.get('bundle_name')} ({b.get('suggested_price')}) -> "
            f"{b.get('items_included')} [{b.get('projected_aov_lift')}]"
        )

    print("\n--- PILLAR 3: ANTI-SPAM SMS (GUT VS. GRAPH) ---")
    for c in pack.get("pillar_3_anti_spam_sms_and_email", {}).get("campaigns", [])[:3]:
        print(f"  [Generic Spam] : {c.get('generic_llm_spam_version')}")
        receipts = ", ".join(c.get("qloo_receipts_cited", []))
        print(f"  [Alfred + Qloo]: {c.get('alfred_qloo_grounded_sms')} (Receipts: {receipts})")

    print("\n--- PILLAR 4: LOCAL BROOKLYN COLLAB & DEAD-NIGHT ACTIVATOR ---")
    collab = pack.get("pillar_4_local_collab_and_dead_night", {})
    pt = collab.get("selected_local_partner", {})
    ev = collab.get("dead_night_activation", {})
    print(f"  Partner : {pt.get('name')} ({pt.get('address')})")
    print(f"  Cold DM : {pt.get('ready_to_send_founder_dm')}")
    print(f"  Event   : {ev.get('event_name')} - {ev.get('concept_and_high_margin_pairing')}")
    print(f"  Playlist: {', '.join(ev.get('vibe_playlist_artists', []))}")

    print("\n--- STAGE 5: GUT VS. GRAPH CONTROL ---")
    print(f"  {gvg.get('control_note', '')}")
    for c in gvg.get("comparisons", []):
        print(f"\n  Decision: {c.get('decision')}")
        print(f"    Blind LLM  : {c.get('blind_llm_without_qloo')}")
        print(f"    Alfred+Qloo: {c.get('alfred_with_qloo')}")
        print(f"    Receipts   : {', '.join(c.get('qloo_receipts', []))}")
        print(f"    Why it wins: {c.get('why_qloo_changes_the_answer')}")

    print("\n--- QUALITY CHECKS ---")
    issues = []

    def scan(obj, path=""):
        if isinstance(obj, str):
            for token in re.findall(r"\[[^\[\]]*\]", obj):
                issues.append(f"{path}: bracketed token {token!r}")
            if "\u2014" in obj:
                issues.append(f"{path}: em dash found")
            for match in re.finditer(
                r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)"
                r"\s+\d{1,2}(?:st|nd|rd|th)?\b",
                obj,
            ):
                issues.append(f"{path}: invented calendar date {match.group(0)!r}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                scan(item, f"{path}[{i}]")
        elif isinstance(obj, dict):
            for key, value in obj.items():
                scan(value, f"{path}.{key}")

    for section in ("focus_group", "execution_pack", "gut_vs_graph"):
        scan(result[section], section)
    if issues:
        for issue in issues:
            print(f"  WARN: {issue}")
    else:
        print("  PASS: no bracketed placeholders or em dashes in generated copy.")

    print("\nSaved complete JSON artifact to alfred_bonafini_output.json")


if __name__ == "__main__":
    main()
