![AgriCatch Logo](docs/logo.png)
=========

[![CI](https://github.com/AZdv/agricatch/actions/workflows/ci.yml/badge.svg)](https://github.com/AZdv/agricatch/actions/workflows/ci.yml)

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

Drop a module in `tech/websites/`. The class name is the module name in title case
(`cnet.py` holds `Cnet`), and discovery picks it up automatically, including in the
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
| `url` | Xpath to a page this one field lives on. Fetched, then `xpath` runs there |

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
hand. Add `child_xpath` when the related fields sit under their own element, as
CNET's Atom byline does.

Extraction produces an inert `RelatedRecord`; nothing is written until
`persist()`. That is what lets an importer be tested against a fixture with no
database at all.

Set `parser = "html"` for pages rather than feeds, and override `hydrate()` when a
record needs fixing up before it is saved (kidsil uses it to absolutize image URLs).

### Crawling more than one page

A feed hands you everything inline. A website usually does not: the listing has a
title and a teaser, and the real content is a click away.

```python
structure = {
    "child_xpath": '//ul[contains(@class,"post-list")]/li',
    "object_url": "h2/a/@href",  # each record's own page
    "pagination": '//a[contains(@href,"/page/")]',  # links to further index pages
    "fields": {...},  # read off the detail page
}
```

| Key | Meaning |
|---|---|
| `object_url` | Xpath to each record's page. `fields` are then read from there |
| `object_url_child_xpath` | Optional. Scope into the detail page before reading `fields` |
| `pagination` | Xpath to further index pages. Followed until the budget runs out |

kidsil uses the first two: its listing carries a ~160 character excerpt while the
posts run past 5,000, so following the link is worth an extra request.

That extra request is the catch: one index page of ten records becomes eleven
fetches, and a `pagination` chain has no natural end. Two class attributes bound it:

```python
class Kidsil(Website):
    crawl_delay = 0.5  # seconds between requests
    max_pages = 12  # hard ceiling for one import
```

Hitting `max_pages` is not an error. The crawl stops, logs where it got to, and
returns everything gathered so far. Pages already fetched are never fetched twice,
and a pagination loop that points back at itself terminates rather than spinning.

Every detail page on an index is fetched as one batch, up to `max_concurrency` at
a time. **Overlapping requests never speeds up the knocking:** `crawl_delay` spaces
the moment each request *starts*, held under a lock, so a site sees at most one new
request every `crawl_delay` seconds however many workers are running. Concurrency
only helps when a server is slow to answer, which is exactly when it matters -
four workers against a host taking twenty seconds to reply finish four times
sooner while requesting at the same rate. There is a test pinning that property,
because it is the one that stops this getting anyone banned.

`collect()` takes a `session` argument (anything with `get(url) -> bytes`), which
is how the crawling tests run against saved pages instead of the network.

Feeds are parsed as XML on purpose. An HTML parse looks like it works and quietly
loses `<link>`, which is a void element in HTML. There's a regression test pinning
this down.

### Custom XPath functions

`agricatch/xpath_functions.py` registers extra functions into lxml, so expressions can
call them directly:

```python
"name": {"xpath": 'make_title(h2/a/text())'}
```

Anything named `xpath_func_<name>` in that module is exposed as `<name>`.

## Geocoding

Geocoding is a lookup, not a calculation: nothing derives coordinates from a name
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

`geocode()` goes through a cache, then OpenStreetMap, then the offline dataset.

Geocoding runs at import time rather than query time, and an aggregator keeps
meeting the same venues, so every distinct place costs exactly one network call
for the lifetime of the database. Results land in `GeocodeCache`; misses are
cached too, or every run re-asks about the places that will never resolve. Pass
`refresh=True` to re-ask anyway.

That ordering matters because **precision decides which queries mean anything.**
At city resolution every venue in Berlin collapses onto one point (measured mean
error 7.9 km, max 14.9 km), so "near Hamburg vs Berlin" works and "within 5 km of
me" is meaningless. OpenStreetMap resolves the actual address; the offline set is
the floor underneath it, for regions and for when the network is gone.

| Layer | Precision | Needs |
|---|---|---|
| `GeocodeCache` | whatever resolved it | nothing, after the first call |
| `NominatimGeocoder` | exact address | network, 1 call/sec |
| `OfflineGeocoder` | city / region | the `geodata/` index |

The offline index comes from a [GeoNames](https://download.geonames.org/export/dump/)
extract (CC BY 4.0) and lives in gitignored `geodata/`, being derived data rebuilt
in one command. Those lookups are pure standard library: no network, no key, no
package. Names fold across case and accents, ambiguous ones resolve to the most
populous match unless you pass `country`, and a long string falls back to its
comma-separated parts so `"Kreuzberg, Berlin"` still finds Berlin. `--alternates`
adds local spellings (`München`, `Firenze`, `東京`) for 2.9 MB instead of 0.7 MB.

Seeding is the slow part: public Nominatim answers in roughly 20 seconds, so a few
hundred venues is a couple of hours, once, in the background. After that it is a
dictionary lookup.

Nothing in `tech` calls this, since articles have no location. It is here for
location-bearing importers, which is where it came from. Use it from an importer's
`hydrate()`, since one lookup fills two columns.

## Distance queries

No PostGIS. A bounding box narrows the candidates on an ordinary index, then the
trigonometry runs on what is left.

```python
from agricatch.geodistance import annotate_distance, filter_within

filter_within(Venue.objects.all(), 52.4990, 13.4180, radius_km=3)
annotate_distance(Venue.objects.all(), 52.4990, 13.4180).order_by("distance")
```

Both return querysets annotated with `distance` in kilometres, nearest first, so
they chain like anything else. `haversine()` is there for two points you already
hold. Pass `lat_field` / `lon_field` if your columns are named differently.

The box is padded by a fraction of a millimetre: it has to be a superset, because
anything it drops never reaches the distance check.

## Tests and checks

```bash
pytest                       # offline, uses saved captures in tests/fixtures/
pytest -m live               # hits the real feeds
ruff check . && ruff format --check .
mypy agricatch tech tests    # everything is annotated, tests included
coverage run -m pytest && coverage report
```

The offline suite runs against real responses recorded from each source, so it checks
actual feed shapes rather than something I made up. It opens no sockets, so it stays
fast and deterministic. The `live` suite is what tells you a source has changed its
layout. Worth running when an importer starts returning nothing.

CI runs the first four on every push across Python 3.11 to 3.13, and checks that the
migrations match the models. The live suite runs weekly on its own schedule rather
than on pushes, so a site having a bad morning never fails a pull request.

Tests carry annotations too, which is not decoration: mypy skips the body of an
unannotated function entirely, so leaving them bare means the test code is the one
part nobody type-checks.

## Notes

Gawker shut down in 2016 and took the old Gizmodo feed with it; CNET has since moved
from RSS to Atom. Both importers were repointed accordingly.
