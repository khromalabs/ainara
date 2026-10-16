# Sample user-contributed search engines

Drop-in engines for Ainara's web meta-search skill (`SearchWeb`), to be
installed by *you*, not by the framework. Contract reference:
`docs/architecture/meta-search.md`.

## Installing an engine

1. Create a directory for your engines, e.g. `~/my_search_engines`.
2. Copy the `.py` file(s) you want into it (one engine per file).
3. Point Ainara at the directory — either in the setup wizard
   (**Skills tab → User Search Engines Directory**) or directly in
   `ainara.yaml`:

   ```yaml
   search:
     web:
       user_engines_directory: /home/you/my_search_engines
   ```

4. Restart Orakle (engines are discovered at startup).

Per-engine settings live under `apis.search.<module name>` in
`ainara.yaml` and are passed to the engine constructor as keyword
arguments. The module (file) name is the engine key and must not shadow
an existing module — such files are refused with a clear error in the
Orakle log.

## Available samples

### `wikipedia_search.py`

Keyless full-text search over Wikipedia (or any MediaWiki installation)
via its public API. Demonstrates the full user-engine contract:

- `REQUIRES_API_KEY = False` — no credentials needed.
- `PARTICIPATION = "specialty"` — vertical engine: it only runs on
  `search_type="encyclopedia"` queries (a search type this engine
  itself registers dynamically) or when requested explicitly by name.
- Config section: `apis.search.wikipedia_search` with optional
  `base_url` (any MediaWiki installation; defaults to
  `https://<language>.wikipedia.org`), `language` (wiki language
  edition, default `en`) and `api_path` (defaults to `/w/api.php`).

Try it after installing (default Orakle port 8100):

```bash
curl -s -X POST http://localhost:8100/run/search_web \
  -H "Content-Type: application/json" \
  -d '{"query": "mount pinatubo eruption", "search_type": "encyclopedia"}'
```

## Writing your own

Start from `wikipedia_search.py`: subclass `SearchEngineBase`, implement
`search()` (return `List[SearchResult]`, degrading to `[]` on failure),
`is_available`, and optionally `get_search_type_specialties()` —
declaring a non-core specialty creates a new `search_type` value that
the router advertises to the LLM at the next Orakle start.

Also pick a participation mode (`PARTICIPATION`), with full knowledge of
the trade-off — both are equally allowed for user engines:

- `"specialty"` (what `wikipedia_search.py` uses): the engine runs only
  for queries whose `search_type` matches one of its declared
  specialties. Right choice for vertical/niche sources: general
  searches stay untouched.
- `"weighted"`: the engine joins **every** search, with influence scaled
  by `get_default_weight(search_type)`. Right choice for a
  general-purpose provider (another web index, a private corpus) that
  should enrich all queries — but its results (and latency) will be
  part of every single search, so set weights accordingly.
