"""Importer discovery.

Importers are plain modules under ``<app>/websites/``. Discovery walks that
package rather than the filesystem so it keeps working from a zip/wheel install.
"""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType
from typing import TYPE_CHECKING

from django.conf import settings

if TYPE_CHECKING:
    from agricatch.website import Website


def _websites_package(app_name: str | None = None) -> ModuleType:
    app_name = app_name or settings.AGRICATCH_APP
    return importlib.import_module(f"{app_name}.websites")


def get_all_importers(app_name: str | None = None) -> list[str]:
    """Return the importer module names, sorted."""
    package = _websites_package(app_name)
    return sorted(name for _, name, is_pkg in pkgutil.iter_modules(package.__path__) if not is_pkg)


def get_importer_choices(app_name: str | None = None) -> list[tuple[str, str]]:
    return [(name, name) for name in get_all_importers(app_name)]


def load_importer(name: str, app_name: str | None = None) -> Website:
    """Instantiate the importer named ``name``.

    Only names returned by :func:`get_all_importers` are accepted, so a caller
    cannot use this to reach an arbitrary module.
    """
    app_name = app_name or settings.AGRICATCH_APP
    if name not in get_all_importers(app_name):
        raise LookupError(f"unknown importer: {name}")

    module = importlib.import_module(f"{app_name}.websites.{name}")
    try:
        importer_class = getattr(module, name.title())
    except AttributeError as exc:
        raise LookupError(f"{module.__name__} defines no {name.title()} class") from exc
    instance: Website = importer_class()
    return instance
