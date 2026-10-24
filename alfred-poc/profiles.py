"""Shared restaurant profiles and safe defaults for the Alfred POC."""

from typing import Any, Dict, List

BONAFINI_FULL_PROFILE: Dict[str, Any] = {
    "name": "Bonafini",
    "address": "663 Flatbush Ave, Brooklyn, NY 11225",
    "neighborhood_city": "Prospect Lefferts Gardens, Brooklyn",
    "lat": 40.6591,
    "lon": -73.9606,
    "website": "https://www.bonafinibk.com/",
    "menu_highlights": [
        "Pappardelle in Braised Short Rib ($24)",
        "Homemade Mushroom Gnocchi with Truffle Oil ($22)",
        "Wood-Fired Neapolitan Margherita & Soppressata Pizzas ($19-$23)",
        "Polpettine (Braised Meatballs with Ricotta) ($15)",
        "$9 Happy Hour Martinis & House Wine Carafes",
        "Weekend Italian Brunch (Eggs Purgatorio, Mimosa Carafes)",
    ],
    "primary_goal": (
        "Fill dead Tuesday/Wednesday nights at full margin and shift Prospect Park "
        "local orders away from DoorDash to direct ordering."
    ),
    "vibe_seeds": [
        "Roberta's",
        "Frankies 457",
        "Khruangbin",
        "A24",
    ],
    "tag_queries": ["italian", "neapolitan pizza", "cocktails", "brunch"],
    "profile_source": "verified_snapshot",
    "location_source": "verified_profile",
}

DEFAULT_PRIMARY_GOAL = (
    "Increase full-margin weeknight traffic and shift orders from delivery apps "
    "to direct ordering."
)

DEFAULT_VIBE_SEEDS: List[str] = [
    "Roberta's",
    "Khruangbin",
    "A24",
    "Sleepy Jones",
]

DEFAULT_MENU_HIGHLIGHTS: List[str] = [
    "House Signature Dish ($22)",
    "Seasonal Pasta ($24)",
    "Craft Cocktail ($14)",
    "Shared Starter ($12)",
    "Weekend Brunch Plate ($18)",
]

DEFAULT_TAG_QUERIES: List[str] = ["restaurant", "dinner", "cocktails", "local"]
