# Qloo Use Cases

Research notes for **allen** - use cases found in Qloo's docs/case studies plus fresh ideas ideated for the Qloo Agentic Hackathon.

Sources are listed at the bottom. Everything here maps to the observable surface of the Insights API.

## What Qloo actually gives you

- **Cross-domain taste graph**: 250M+ entities across artists, books, brands, destinations, movies, people, places, podcasts, TV shows, video games.
- **Insights API** (`GET /v2/insights`): input entities/tags/audiences/demographics/location → return ranked entities with **affinity score (0..+1)** and **popularity**.
- **Supporting APIs**: `/search` (resolve names → Qloo IDs), `/v2/tags` (find valid tag IDs), audiences, Analysis Compare (compare two entity groups), Trending Data (time-series popularity), Taste Analysis (tag metadata).
- **Privacy by design**: no identity graph, no PII required, stateless inference, aggregate affinities only.

## Capability → use-case patterns (from the docs)

| Pattern | How | Example product |
| --- | --- | --- |
| Top recommendations | `signal.interests.entities` → ranking in `filter.type` | "More like this" across catalogs |
| Audience alignment | entities/tags as signal, demographics/audiences as filter | Which audiences over-index on this artist/brand |
| Geographic affinity | `filter.location.query` + entity signals | Map where a taste is concentrated |
| Geo-tailored results | same signals, scoped to a location | Block-level local recs (Michelin/Tablet Hotels) |
| Metadata / tag discovery | Taste Analysis + `/v2/tags` | Genre/cuisine/style exploration |
| Comparison | Analysis Compare on two groups | Brand A fans vs Brand B fans |
| Trend tracking | Trending Data time series | Early signal on rising entities |

## Validated use cases (found, with proof points)

### Travel & hospitality
- **Bespoke itineraries** from a hotel's/guest's style profile, not geography (Michelin's Tablet Hotels: **+273% bookings** in A/B test).
- **Cold-start acquisition**: recommend destinations with zero first-party data.
- **In-flight curation**: entertainment + dining per passenger taste.
- **Personalized rewards** to drive loyalty.

### Retail & commerce
- **Tailored product recs** and assortment fits by neighborhood.
- **Smarter stores**: where to build, how to design, what to stock.
- **Partner/influencer selection**: who the audience actually relates to.
- **Ad targeting & campaign optimization** (retails' media networks).
- **First-party data enrichment**: jewelry brand widened its customer reach via taste lookalikes.

### Media & entertainment
- **Discovery across catalogs** from a single title outward (Netflix merchandising partnerships; Tinder et al. drove **+70% engagement** for Match Group).
- **Cookie-less media planning/personalization** (JCDecaux hyper-local DOOH).
- **Donor/audience growth** for causes (Special Olympics).

### AI/LLM grounding
- **Ground LLMs/agents in real taste data**: tailored recs, customized responses, content adaptation, RAG with cultural context - the reason this hackathon exists ("agents are culturally blind").
- **Cold start**: one signal is enough to generate recommendations.

## Hackathon prompt examples (from the official brief)

- Electrician's customers choosing **lighting styles per room** (mood, comfort, function).
- **Senior meals/dining** agent: taste + health constraints (easy-to-chew, low-heat, medication-aware).
- **Rare-disease journey companion**: mix of information + community + next steps by emotional and practical need.

Judging: Technological Implementation, Design, Quality of the Idea (equally weighted). Demo must be hosted publicly; repo public with open-source license. Requirement: it must **not** work the same without Qloo.

## Prior hackathon projects (found)

- **Culturo** - "Spotify of cultural tastes" spanning travel, food, fashion, media.
- **Qlootra** - taste-driven travel companion covering pre-trip, in-transit, and destination.
- **PersonaReads** - book recs from reading persona/tone/themes.
- **Taste Taylor** - multi-agent fashion editorial generation.
- **Fashion rec system** - Qdrant + Gemini: anti-recommendations, fashion twin, mixed-culture styles.
- **TasteTable** - caregiver's planning assistant; tool-calling loop over Qloo with hard constraint checks.

## Ideated concepts

Each idea uses affinity + popularity outputs, so "hidden gem" (high affinity, low popularity) and "mainstream" (high popularity) modes are first-class.

### Discovery & entertainment
1. **Anti-Algorithm** - an agent that deliberately surfaces high-affinity, *low-popularity* music, movies, books, and places with a slider from "safe pick" to "you've never heard of this." Killer demo: same taste vector, drastically different popularity bands.
2. **Taste Time Machine** - enter a movie/album you loved in a decade; get that era's adjacent culture (places, brands, books) plus what modern equivalents exist now. Uses cross-domain affinity + trending data to compare eras.
3. **Book-to-Screen Matchmaker** (or reverse) - given a book, rank movies and vice versa; extend to "what should we adapt next" for studios using affinity + popularity as a commercial signal.
4. **Group Taste Mediator** - multiple people's entities as signals; agent negotiates a movie/restaurant/activity that maximizes joint affinity. Great party trick, genuinely hard to do without the graph.
5. **Festival Lineup Alchemist** - given a headliner, generate a coherent lineup (artists) plus lodging/dining for attendees in `filter.location`; agent balances affinity vs. budget constraints.

### Travel & local
6. **Where Your Taste Lives** - "You love Wes Anderson and Tokyo jazz bars; here are three neighborhoods on Earth that are literally your taste." Destination/place recs + geographic affinity visualization.
7. **Same Block, Different World** - two hotels 200 feet apart get two completely different itineraries (the Michelin demo, productized for any city).
8. **Hour-by-Hour Local Twin** - an agent that builds a walking day plan (place) from a traveler's artist/book/brand signals; recalibrates live as they rate things during the day.
9. **Relocation Radar** - agent that matches a person to cities/neighborhoods by taste fit, not just jobs or rent data.

### Commerce & marketing
10. **Partnership Oracle** - brands upload their audience signals; agent finds co-marketing partners, influencers, and collab concepts ranked by audience overlap (Analysis Compare). Pitch deck generator included.
11. **Neighborhood Concept Fit** - real estate/restaurant concept scoring: "Would a listening bar work at this address?" Uses location-scoped affinity + demographic audiences; outputs a fit score, comparable venues, and a risk read.
12. **Trend Early-Warning Desk** - brand-side agent monitoring trending entities; when a tag/artist/place inflects upward, it proposes campaigns, products, or local activations with the audience breakdown attached.
13. **Gift Whisperer** - cross-domain gifting: input any entity a person loves (band, team, show, book) → candidate gifts across brands/books/movies/places, filtered by budget/occasion and popularity preference.

### Health, accessibility & community
14. **Night-Out, Medically Safe** - seniors/chronic-illness agent combining taste (places, cuisines) with constraints: noise level, seating, low-sodium/low-heat menus, medication interactions. (TasteTable-style constraint loop.)
15. **Care Compass** (rare disease) - maps a patient's taste/personality signals to supportive literature, podcasts, communities, and places, ranked by emotional fit as well as relevance.
16. **Sensory-Safe City Guide** - for autistic/neurodivergent users: quiet venues, low-stimulation events, and media matching their known favorite entities.

### Culture & creative tools
17. **Muse Agent** - for creators: "I make X; what adjacent genres/themes/brands should I borrow from?" Uses tag metadata + cross-domain affinity for moodboards, soundtrack, and merch tie-ins.
18. **Wedding/Party Architect** - couples blend two taste vectors → DJ setlist artists, venue places, destination honeymoon, and invitation brand aesthetic.

## Rules of thumb (from the developer guide)

- Base URL `https://hackathon.api.qloo.com` only; auth via `X-Api-Key` header; `/v2/insights` is **GET** with dotted query params.
- `filter.type` required; valid types: `artist`, `book`, `brand`, `destination`, `movie`, `person`, `place`, `podcast`, `tv_show`, `video_game`. Use `place`/`brand` for food & drink, `artist` for music.
- Invalid params are silently ignored → empty results. Validate tags/audiences via `/v2/tags` and audience lookup first.
- Never use `/recs` or `/recommendations` (legacy). Do not store response data in a public repo; private server-side caching is fine.
- Outputs are aggregate affinities - never present them as facts about an individual.

## Sources

- Hackathon developer guide: https://docs.qloo.com/reference/qloo-llm-hackathon-developer-guide
- API overview: https://docs.qloo.com/reference/api-overview
- Insights API: https://docs.qloo.com/reference/insights-api-deep-dive
- Devpost brief/rules: https://qloo.devpost.com/ and https://qloo.devpost.com/rules
- Hackathon kit (CLI/MCP/agent routes): https://github.com/qloo/qloo-hackathon-kit
- Qloo case studies: Michelin/Tablet Hotels (+273% bookings), Match Group (+70% engagement), Netflix merchandising, JCDecaux DOOH, Special Olympics donor engagement - https://www.qloo.com/resources
- Industry pages: https://www.qloo.com/industries/travel-hospitality , https://www.qloo.com/industries/retail
- Prior projects: https://qloo-hackathon.devpost.com/project-gallery , https://github.com/Celestial317/qloo-hackathon , https://github.com/Jacob-Met/tastetable
