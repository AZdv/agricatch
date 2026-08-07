# Where these fixtures came from

## Synthetic, written for this repo

`techcrunch.xml`, `gizmodo.xml`, `cnet.xml`

Not captures. They are written to match the *structure* of the feeds the
matching importers read, which is the part the tests care about:

- **`techcrunch.xml`, `gizmodo.xml`** - RSS 2.0. `<link>` carries the URL as
  element text, which is exactly the case an HTML parser silently drops, and
  `dc:creator` sits in the Dublin Core namespace. Both are pinned by tests.
- **`cnet.xml`** - Atom. `<entry>` rather than `<item>`, a default namespace, the
  link as an attribute, a nested `<author><name>`, and a `media:content` image.
  `published` is deliberately much older than `updated`, as it is on real
  evergreen articles, because the importer reads `updated` for that reason.

The headlines, summaries and bylines are invented. Earlier revisions of this
repo used real captures; they were replaced so a public repo is not
redistributing other people's articles.

## Real, and the author's own site

`kidsil.html`, `kidsil-page2.html`, `kidsil-detail.html`

Captures of https://www.kidsil.net/, which belongs to the author of this
project. Kept real because the HTML scraping path is worth testing against
markup nobody tidied up for the occasion: a listing page, its `?page=2`
continuation, and one post's own page.

## Third-party data, redistributed under its licence

`geodata-sample.tsv.gz`

A 16-row slice of a [GeoNames](https://www.geonames.org/) extract, reduced to
the columns the geocoder indexes. GeoNames data is licensed
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); this file is a
derivative of it and carries the same terms, with attribution to GeoNames.

It is here so the offline geocoder can be tested without downloading the full
extract. The real index is built by `manage.py fetch_geodata` and is gitignored.
