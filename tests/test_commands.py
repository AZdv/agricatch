"""The management commands, which are how anyone actually drives this."""

import gzip
import io
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from agricatch.website import ImportResult, Website

# name, asciiname, alternatenames, lat, lon, ..., country, ..., population
GEONAMES_ROWS = "\n".join(
    [
        "\t".join(
            ["1", "Berlin", "Berlin", "Berlino", "52.52437", "13.41053", "P", "PPLC", "DE"]
            + [""] * 5
            + ["3426354", "", "74", "Europe/Berlin", "2024-01-01"]
        ),
        "\t".join(
            ["2", "Springfield", "Springfield", "", "37.21533", "-93.29824", "P", "PPLA2", "US"]
            + [""] * 5
            + ["170188", "", "394", "America/Chicago", "2024-01-01"]
        ),
        # A second Springfield: distinct place, same name.
        "\t".join(
            ["3", "Springfield", "Springfield", "", "39.79947", "-89.64371", "P", "PPLA", "US"]
            + [""] * 5
            + ["114394", "", "170", "America/Chicago", "2024-01-01"]
        ),
        "short\tline",
    ]
)


class StubImporter(Website):
    """Records that it ran, without touching the network."""

    calls: list[int] = []
    url_info = {"url": "https://example.com/"}
    structure = {"child_xpath": "//item", "fields": {}}

    def do_import(self, days: int = 1, start_day: Any = None, url: Any = None) -> ImportResult:
        StubImporter.calls.append(days)
        return ImportResult(created=2, updated=1)


@pytest.fixture(autouse=True)
def reset_stub() -> None:
    StubImporter.calls = []


# ---- doimport --------------------------------------------------------


def test_doimport_runs_the_named_importer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "tech.management.commands.doimport.load_importer", lambda name: StubImporter()
    )
    out = io.StringIO()
    call_command("doimport", "techcrunch", stdout=out)

    assert StubImporter.calls == [1]
    assert "Importing from techcrunch" in out.getvalue()
    assert "2 new, 1 updated" in out.getvalue()


def test_doimport_passes_the_days_option(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "tech.management.commands.doimport.load_importer", lambda name: StubImporter()
    )
    call_command("doimport", "techcrunch", days=5, stdout=io.StringIO())
    assert StubImporter.calls == [5]


def test_doimport_with_no_name_runs_every_importer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "tech.management.commands.doimport.load_importer", lambda name: StubImporter()
    )
    call_command("doimport", stdout=io.StringIO())
    assert len(StubImporter.calls) == 4  # cnet, gizmodo, kidsil, techcrunch


def test_doimport_rejects_an_unknown_importer() -> None:
    with pytest.raises(CommandError, match="unknown importer"):
        call_command("doimport", "not-a-real-site", stdout=io.StringIO())


def test_doimport_reports_when_nothing_is_discoverable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tech.management.commands.doimport.get_all_importers", lambda: [])
    with pytest.raises(CommandError, match="no importers found"):
        call_command("doimport", stdout=io.StringIO())


# ---- fetch_geodata ---------------------------------------------------


def fake_zip(name: str = "cities15000") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{name}.txt", GEONAMES_ROWS)
    return buffer.getvalue()


def stub_download(monkeypatch: pytest.MonkeyPatch, payload: bytes) -> None:
    class Response:
        content = payload

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(
        "tech.management.commands.fetch_geodata.httpx.get",
        lambda *a, **k: Response(),
    )


def test_fetch_geodata_writes_an_index(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    stub_download(monkeypatch, fake_zip())
    target = tmp_path / "cities.tsv.gz"

    call_command("fetch_geodata", output=str(target), stdout=io.StringIO())

    assert target.exists()
    rows = gzip.open(target, "rt", encoding="utf-8").read().strip().split("\n")
    assert len(rows) == 3
    assert rows[0].split("\t")[:2] == ["berlin", "Berlin"]


def test_fetch_geodata_keeps_distinct_places_sharing_a_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Both Springfields must survive; the geocoder picks between them later."""
    stub_download(monkeypatch, fake_zip())
    target = tmp_path / "cities.tsv.gz"
    call_command("fetch_geodata", output=str(target), stdout=io.StringIO())

    keys = [line.split("\t")[0] for line in gzip.open(target, "rt", encoding="utf-8")]
    assert keys.count("springfield") == 2


def test_fetch_geodata_can_index_alternate_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stub_download(monkeypatch, fake_zip())
    target = tmp_path / "alt.tsv.gz"
    call_command("fetch_geodata", output=str(target), alternates=True, stdout=io.StringIO())

    keys = {line.split("\t")[0] for line in gzip.open(target, "rt", encoding="utf-8")}
    assert "berlino" in keys


def test_fetch_geodata_reports_a_download_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def explode(*args: Any, **kwargs: Any) -> None:
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr("tech.management.commands.fetch_geodata.httpx.get", explode)
    with pytest.raises(CommandError, match="could not download"):
        call_command("fetch_geodata", output=str(tmp_path / "x.gz"), stdout=io.StringIO())


def test_fetch_geodata_skips_malformed_lines(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The trailing 'short\tline' row has too few columns to be a place."""
    stub_download(monkeypatch, fake_zip())
    target = tmp_path / "cities.tsv.gz"
    call_command("fetch_geodata", output=str(target), stdout=io.StringIO())

    names = {line.split("\t")[1] for line in gzip.open(target, "rt", encoding="utf-8")}
    assert names == {"Berlin", "Springfield"}
