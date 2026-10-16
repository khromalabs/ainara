# Meta-search subsystem reference

Technical reference for the web meta-search (`SearchWeb` skill and its
engine pool). Contract-level documentation: what exists, where it lives,
and the invariants that must hold. Design history and decisions live in
[issue #22](https://github.com/khromalabs/ainara/issues/22).

## Overview

`ainara/orakle/skills/search/web.py` (`SearchWeb`) runs a meta-search:
it fans a query out to a pool of search engines in parallel, fuses and
dedups the results, and returns normalized results. Engines are pluggable
in two ways:

- **Core engines** live in `ainara/orakle/skills/search/web_engines/`
  (one class per module, auto-discovered).
- **User-contributed engines** are regular engine modules in a filesystem
  directory pointed at by `search.web.user_engines_directory`. They use
  the exact same contract and join the pool exactly like core engines.

The tiered skills model (issue #17) applies by *location*: core engines
ship with the framework; user engines live on the user's system; a future
curated repository can distribute engines into an optional directory.

## Engine contract (`SearchEngineBase`)

File: `ainara/orakle/skills/search/web_engines/base.py`. One engine per
module; the engine key is the module name; core engines win name
collisions.

| Member | Meaning |
|---|---|
| `async search(query, num_results=5, **kwargs)` | Returns `List[SearchResult]`. Degrade silently (log + return `[]`) on failure — the meta-search must survive one broken engine. |
| `is_available` (property) | Whether the engine joins the pool. Keyed engines: API key present. Keyless engines: config section sufficient (e.g. SearXNG needs `base_url`). |
| `REQUIRES_API_KEY: bool` | `True` (default): instantiated only when `apis.search.<name>.api_key` exists. `False`: instantiated from the (possibly empty) config section; availability is the engine's own decision via `is_available`. |
| `get_search_type_specialties()` | Search types the engine is optimized for. Declaring a type **creates** it: non-core specialties become new `search_type` values dynamically (see below). |
| `get_default_weight(search_type)` | Influence in weighted fusion for a search type. |
| `PARTICIPATION: str` | `"weighted"` (default): joins every eligible search. `"specialty"`: only joins searches whose `search_type` matches a declared specialty. Intended for vertical engines. |

Per-engine settings live under `apis.search.<engine name>` in
`ainara.yaml` (declared in `resources/config.schema.json`). Keyless
engines receive their whole config section as constructor kwargs.

## Dynamic search types and participation

Valid `search_type` values = `SearchWeb.CORE_SEARCH_TYPES`
(`comprehensive`, `academic`, `recent`, `exploratory`, `news`, `crypto`)
plus every specialty declared by an engine currently in the pool. The
`search_type` parameter annotation is rebuilt as a dynamic `Literal` at
init, so the LLM-facing capability schema always reflects the live pool.

Selection rules (`SearchWeb._apply_participation`):

- **Core search types**: classic behavior — `"weighted"` engines join
  everything; `"specialty"` engines only when the type matches.
- **Vertical search types** (declared by at least one engine, not core):
  *exclusive* — only engines declaring the type participate, so a
  `jobs` query is not diluted with general web results.
- Explicitly requested engines (`engine` parameter) always run.
- If nothing survives the filter, the full pool is used so a search
  never returns nothing.

## Result model (`SearchResult`)

`title`, `link` (the **original** offer/page URL — vertical sources
require attribution), `snippet`, `provider`, plus optional
`relevance_score`, `published_date`, `source_engine`, `author`,
`image_url`.

`metadata: Dict[str, Any]` is engine-defined structured data for
vertical results (e.g. jobs: `company`, `salary_min/max`,
`salary_currency`, `salary_period`, `location`, `tags`, `source`). The
base class is topic-agnostic: key names and semantics belong to each
engine; consumers treat unknown keys as opaque. Engines that populate
`metadata` should also surface a human-readable summary in `snippet` —
that is what fusion and response synthesis consume.

Dedup: the framework dedups by normalized URL; vertical engines with
URL-variant duplicates (same offer cross-posted) should dedup internally
before returning.

## User-contributed engines

Users own their machines and their code: any engine a user installs is
trusted to declare whatever participation mode fits its purpose. The
framework does not restrict user engines — the two modes just have
different, clearly documented consequences so the choice is an informed
one:

- `"specialty"` (recommended for vertical engines): the engine only runs
  when the search `search_type` matches one of its declared specialties
  (or is explicitly requested). General searches are untouched.
- `"weighted"`: the engine joins **every** meta-search, with influence
  scaled by its `get_default_weight(search_type)`. This is the right
  choice for a general-purpose provider meant to enrich all queries
  (e.g. another web index, a private corpus). Be aware the engine's
  results will appear on every search — a niche or slow source will
  dilute and slow down general searches, so pick weights accordingly.

1. Set the directory in `ainara.yaml` (or in the setup wizard,
   **Skills tab → User Search Engines Directory**):
   ```yaml
   search:
     web:
       user_engines_directory: /path/to/engines
   ```
2. Drop one engine per `.py` file; each file subclasses
   `SearchEngineBase`. Per-engine settings go under
   `apis.search.<module name>`.
3. Restart Orakle (discovery happens at startup; the modified-after-
   startup guard applies, same as user skills).

Safety: a user module whose name would shadow an existing module
(stdlib, installed package, core engine) is **refused** with a clear
error instead of imported (the sys.path shadowing hazard flagged for
user skills in #17). Files starting with `_` are skipped.

Example minimal engine (a complete, working sample ships in
`resources/examples/user_web_engines/wikipedia_search.py`):

```python
from ainara.orakle.skills.search.web_engines.base import (
    SearchEngineBase, SearchResult)

class MyVertical(SearchEngineBase):
    """One-line description (feeds the capability docstring)."""
    REQUIRES_API_KEY = False
    PARTICIPATION = "specialty"

    @property
    def is_available(self):
        return True

    def get_search_type_specialties(self):
        return ["myvertical"]   # creates search_type='myvertical'

    async def search(self, query, num_results=5, **kwargs):
        ...  # fetch, normalize, dedup
        result = SearchResult(title=..., link=..., snippet=..., provider="myvertical")
        result.source_engine = "myvertical"
        result.metadata = {...}   # engine-defined structured fields
        return [result]
```

## Capabilities schema: two audiences, one timing invariant

The capability metadata serves two consumers:

- **Router/matcher**: `matcher_info`, `description`,
  `embeddings_boost_factor` decide *whether* the skill handles a request.
- **Argument-filling LLM**: `run_info.parameters` decides *what
  arguments to pass*. Keep this surface small; internal plumbing
  (`**kwargs`) should be marked `"hidden"` in the `Annotated` metadata
  so the llm view of `GET /capabilities` drops it.

**Timing invariant**: `run_info` is introspected *after* skill
instantiation during discovery. Anything that mutates the LLM-facing
signature or class docstring (dynamic `Literal`s, generated docstrings)
must happen in `__init__` — never in a post-discovery hook. SearchWeb's
docstring is set on the **class** (`type(self).__doc__`), because
discovery reads `instance.__class__.__doc__`; an instance-attribute
assignment only shadows it.

## Testing recipes

Direct Orakle invocation (default `http://127.0.0.1:8100`):

```bash
# What the LLM sees (lean) vs full schema
curl -s http://localhost:8100/capabilities | python3 -m json.tool
curl -s "http://localhost:8100/capabilities?view=full" | python3 -m json.tool

# Execute a skill
curl -s -X POST http://localhost:8100/run/search_web \
  -H "Content-Type: application/json" \
  -d '{"query": "senior python developer", "search_type": "jobs", "num_results": 10}'
```

Offline engine development: instantiate the engine directly against a
stubbed config and drive `search()`; the jobs engine
(`user_engines/jobs.py` model) also caches raw source payloads in SQLite
(`get_data_dir()/search/`), which doubles as recorded fixtures.
