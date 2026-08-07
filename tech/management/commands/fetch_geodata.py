"""Build the offline geocoding index from a GeoNames extract.

The output is deliberately not committed - it is derived data, and regenerating
it is one command. See https://download.geonames.org/export/dump/ for the
available extracts; they are CC BY 4.0.
"""

import csv
import gzip
import io
import zipfile
from pathlib import Path

import httpx
from django.core.management.base import BaseCommand, CommandError

from agricatch.geocode import DEFAULT_DATASET, FIELDNAMES, normalize

BASE_URL = "https://download.geonames.org/export/dump"

# name, asciiname, alternatenames, latitude, longitude, country, population
COLUMNS = {"name": 1, "ascii": 2, "alternates": 3, "lat": 4, "lon": 5, "country": 8, "pop": 14}

DATASETS = {
    "cities15000": "cities with over 15,000 people (~34k, smallest useful)",
    "cities5000": "cities with over 5,000 people (~55k)",
    "cities500": "cities with over 500 people (~200k, most thorough)",
}


class Command(BaseCommand):
    help = "Download a GeoNames extract and build the offline geocoding index."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dataset",
            default="cities15000",
            choices=sorted(DATASETS),
            help="which GeoNames extract to use",
        )
        parser.add_argument("--output", default=None, help="where to write the index")
        parser.add_argument(
            "--alternates",
            action="store_true",
            help="also index alternate names (bigger, but matches local spellings)",
        )

    def handle(self, *args, **options):
        dataset = options["dataset"]
        output = Path(options["output"] or DEFAULT_DATASET)
        url = f"{BASE_URL}/{dataset}.zip"

        self.stdout.write(f"Downloading {url}")
        try:
            response = httpx.get(url, timeout=120.0, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CommandError(f"could not download {url}: {exc}") from exc

        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            raw = archive.read(f"{dataset}.txt").decode("utf-8")

        output.parent.mkdir(parents=True, exist_ok=True)
        rows = self.build_rows(raw, include_alternates=options["alternates"])

        with gzip.open(output, "wt", encoding="utf-8", newline="") as handle:
            csv.DictWriter(handle, fieldnames=FIELDNAMES, delimiter="\t").writerows(rows)

        size_mb = output.stat().st_size / 1024 / 1024
        self.stdout.write(
            self.style.SUCCESS(f"Wrote {len(rows)} keys to {output} ({size_mb:.1f} MB)")
        )

    def build_rows(self, raw, include_alternates=False):
        """Flatten the extract into one row per searchable name.

        Distinct places that share a name each keep their own row - there are
        three Berlins and a dozen Springfields, and the geocoder picks between
        them by population and country.
        """
        rows = []
        for line in raw.splitlines():
            parts = line.split("\t")
            if len(parts) <= COLUMNS["pop"]:
                continue

            name = parts[COLUMNS["name"]]
            names = [name, parts[COLUMNS["ascii"]]]
            if include_alternates:
                names += parts[COLUMNS["alternates"]].split(",")

            # Only collapses spellings of *this* place, e.g. name == asciiname.
            seen = set()
            for candidate in names:
                key = normalize(candidate)
                if not key or key in seen:
                    continue
                seen.add(key)
                rows.append(
                    {
                        "key": key,
                        "name": name,
                        "latitude": parts[COLUMNS["lat"]],
                        "longitude": parts[COLUMNS["lon"]],
                        "country": parts[COLUMNS["country"]],
                        "population": parts[COLUMNS["pop"]] or "0",
                    }
                )
        return rows
