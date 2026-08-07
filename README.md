![AgriCatch Logo](https://azdv.github.io/agricatch/images/logo.png)
=========

Declarative data aggregation for Django.

This started as an algorithm I wrote in vanilla PHP, then moved to Yii. Eventually I
rewrote the whole thing in Python (third time's a charm) on Django. This is the 2.0
version of that: same idea, now on Python 3 and Django 5.

An importer says *where* the data is, not how to walk it. You give it a URL and a set
of XPath-addressed fields, and the base class handles fetching, parsing, extraction,
type coercion and de-duplication.

```python
from agricatch.website import Website


class Techcrunch(Website):
    namespaces = {"dc": "http://purl.org/dc/elements/1.1/"}
    url_info = {"url": "https://techcrunch.com/feed/"}
    structure = {
        "child_xpath": "//channel/item",
        "fields": {
            "name": {"xpath": "title/text()"},
            "link": {"xpath": "link/text()"},
            "time": {"type": "time", "xpath": "pubDate/text()"},
            "author": {
                "type": "table",
                "model": "Author",
                "lookup": ["name"],
                "required": False,
                "fields": {"name": {"xpath": "dc:creator/text()"}},
            },
        },
    }
```

That is the entire TechCrunch importer.

## Running it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env          # then fill in DJANGO_SECRET_KEY
export DJANGO_DEBUG=1

python manage.py migrate
python manage.py doimport techcrunch --days=1
python manage.py runserver
```

`doimport` with no importer name runs all of them.

## Endpoints

| Path | What it does |
|---|---|
| `GET /agricatch/articles` | JSON list. `sort_by`, `days_future`, `limit`, `last_update` |
| `GET /agricatch/article/<id>` | Single article |
| `GET,POST /agricatch/importform` | Run an importer from the browser. Staff only |

`sort_by` is checked against a fixed set of fields, since it ends up in `ORDER BY`.

## Writing an importer

Drop a module in `tech/websites/`. The class name is the module name in title case —
`cnet.py` holds `Cnet` — and discovery picks it up automatically, including in the
import form's dropdown.

Field options:

| Key | Meaning |
|---|---|
| `xpath` | Expression, evaluated relative to the record node |
| `type` | `normal` (default), `time`, or `table` |
| `required` | Drop the whole record if missing. Defaults to true |
| `format` | `time` only. `%STR%` is the matched text, `%TIME%` the crawl date |
| `remove` | `time` only. Substrings stripped before parsing |
| `function` | Name of an `agricatch.helpers.text` callable to apply |

### Related tables

`type: table` fills a foreign key from fields nested inside the same record. The
author on every feed importer works this way:

```python
"author": {
    "type": "table",
    "model": "Author",
    "lookup": ["name"],
    "required": False,
    "fields": {"name": {"xpath": "dc:creator/text()"}},
},
```

| Key | Meaning |
|---|---|
| `model` | Target model in the app named by `AGRICATCH_APP` |
| `fields` | Nested field specs. Same options, including another `table` |
| `lookup` | Fields matched against existing rows. Defaults to all of them |
| `child_xpath` | Optional. Scope into a sub-element before reading `fields` |

Matching is get-or-create on `lookup`, so re-importing reuses the existing row
instead of duplicating it, and never overwrites a row you have since corrected by
hand. Add `child_xpath` when the related fields sit under their own element —
CNET's Atom byline is nested that way.

Extraction produces an inert `RelatedRecord`; nothing is written until
`persist()`. That is what lets an importer be tested against a fixture with no
database at all.

Set `parser = "html"` for pages rather than feeds, and override `hydrate()` when a
record needs fixing up before it is saved (kidsil uses it to absolutize URLs).

Feeds are parsed as XML on purpose. An HTML parse looks like it works and quietly
loses `<link>`, which is a void element in HTML — there's a regression test pinning
this down.

### Custom XPath functions

`agricatch/xpath_functions.py` registers extra functions into lxml, so expressions can
call them directly:

```python
"name": {"xpath": 'make_title(h2/a/text())'}
```

Anything named `xpath_func_<name>` in that module is exposed as `<name>`.

## Geocoding

Geocoding is a lookup, not a calculation — nothing derives coordinates from a name
without reference data. So the only real question is which dataset you carry.

```bash
python manage.py fetch_geodata                # ~34k cities, 0.7 MB
python manage.py fetch_geodata --alternates   # + local spellings, 2.9 MB
```

```python
from agricatch.geocode import geocode

geocode("Berlin")  # Location(name='Berlin', latitude=52.52, ..., country='DE')
geocode("Paris", country="US")  # the one in Texas
```

The index is built from a [GeoNames](https://download.geonames.org/export/dump/)
extract (CC BY 4.0) and lives in `geodata/`, which is gitignored — it is derived
data, and rebuilding it is one command. Lookups are pure standard library: no
network, no API key, no third-party package. Names fold across case and accents,
ambiguous names resolve to the most populous match unless you pass `country`, and
a longer string falls back to its comma-separated parts, so `"Kreuzberg, Berlin"`
still finds Berlin.

`--alternates` indexes local spellings, so `München`, `Firenze`, `Moskva` and
`東京` resolve. It costs 2.9 MB instead of 0.7 MB and about a second of load time.

**What it will not do is street addresses or venues.** That needs OpenAddresses or
a full OSM extract — hundreds of gigabytes, not something to ship in a repo. When
you need that precision, `NominatimGeocoder` asks OpenStreetMap instead. It needs
the network and is rate limited to one call a second by OSM's usage policy.

```python
from agricatch.geocode import NominatimGeocoder, geocode

geocode("Berghain, Berlin", geocoder=NominatimGeocoder())
```

Nothing in `tech` calls this — articles have no location. It is here for
location-bearing importers, which is where it came from. Use it from an importer's
`hydrate()`, since one lookup fills two columns.

## Tests

```bash
pytest              # offline, uses saved captures in tests/fixtures/
pytest -m live      # hits the real feeds
```

The offline suite runs against real responses recorded from each source, so it checks
actual feed shapes rather than something I made up. The `live` suite is what tells you
a source has changed its layout — worth running when an importer starts returning
nothing.

## Notes

Gawker shut down in 2016 and took the old Gizmodo feed with it; CNET has since moved
from RSS to Atom. Both importers were repointed accordingly.
