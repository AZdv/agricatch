from __future__ import annotations

from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from agricatch.helpers.general import get_all_importers, load_importer


class Command(BaseCommand):
    help = "Import articles from one or more websites. With no name, runs every importer."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("importers", nargs="*", help="importer names, e.g. techcrunch")
        parser.add_argument("-d", "--days", type=int, default=1, help="days back to crawl")

    def handle(self, *args: Any, **options: Any) -> None:
        names = options["importers"] or get_all_importers()
        if not names:
            raise CommandError("no importers found")

        for name in names:
            try:
                importer = load_importer(name)
            except LookupError as exc:
                raise CommandError(str(exc)) from exc

            self.stdout.write(f"Importing from {name}")
            result = importer.do_import(days=options["days"])
            self.stdout.write(
                self.style.SUCCESS(
                    f"  {result.created} new, {result.updated} updated, {result.skipped} skipped"
                )
            )
