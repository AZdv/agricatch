"""Importer discovery.

Importers are plain modules under ``<app>/websites/``. Discovery walks that
package rather than the filesystem so it keeps working from a zip/wheel install.
"""

import importlib
import pkgutil

from django.conf import settings


def _websites_package(app_name=None):
    app_name = app_name or settings.AGRICATCH_APP
    return importlib.import_module(f"{app_name}.websites")


def get_all_importers(app_name=None):
    """Return the importer module names, sorted."""
    package = _websites_package(app_name)
    return sorted(name for _, name, is_pkg in pkgutil.iter_modules(package.__path__) if not is_pkg)


def get_importer_choices(app_name=None):
    return [(name, name) for name in get_all_importers(app_name)]


def load_importer(name, app_name=None):
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
    return importer_class()
