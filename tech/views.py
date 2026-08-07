from __future__ import annotations

import datetime

from django.contrib.admin.views.decorators import staff_member_required
from django.core.cache import cache
from django.db.models import Max
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from agricatch.helpers.general import load_importer
from tech.forms import ImportForm
from tech.models import Article

# order_by() takes a field name straight into SQL, so the accepted values are
# fixed here rather than taken from the query string.
SORTABLE_FIELDS = frozenset({"time", "-time", "added_at", "-added_at", "name", "-name"})
DEFAULT_LIMIT = 100
MAX_LIMIT = 500
LAST_UPDATE_CACHE_KEY = "tech:articles:last_update"
LAST_UPDATE_CACHE_SECONDS = 2 * 60 * 60


class BadParameter(ValueError):
    """A query-string value that could not be read as asked for."""


def _int_param(request: HttpRequest, name: str, default: int | None) -> int | None:
    raw = request.GET.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise BadParameter(f"{name} must be an integer") from exc


@require_http_methods(["GET"])
def articles(request: HttpRequest) -> HttpResponse:
    if "last_update" in request.GET:
        return JsonResponse({"last_update": _last_update()})

    try:
        requested_limit = _int_param(request, "limit", DEFAULT_LIMIT)
        days_future = _int_param(request, "days_future", None)
    except BadParameter as exc:
        return HttpResponseBadRequest(str(exc))

    limit = max(1, min(requested_limit or DEFAULT_LIMIT, MAX_LIMIT))
    queryset = Article.objects.select_related("website", "author")

    sort_by = request.GET.get("sort_by")
    if sort_by is not None:
        if sort_by not in SORTABLE_FIELDS:
            return HttpResponseBadRequest(
                "sort_by must be one of: " + ", ".join(sorted(SORTABLE_FIELDS))
            )
        queryset = queryset.order_by(sort_by)

    if days_future is not None:
        # Measured from the start of today, so this morning's articles still count.
        start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
        queryset = queryset.filter(
            time__gte=start, time__lte=start + datetime.timedelta(days=days_future)
        )

    payload = [
        {
            "id": article.pk,
            "name": article.name,
            "description": article.description,
            "link": article.link,
            "image": article.image,
            "author": article.author.name if article.author else None,
            "time": article.time.isoformat() if article.time else None,
            "added_at": article.added_at.isoformat(),
            "website": article.website.slug if article.website else None,
        }
        for article in queryset[:limit]
    ]
    return JsonResponse({"count": len(payload), "results": payload})


def _last_update() -> str | None:
    cached = cache.get(LAST_UPDATE_CACHE_KEY)
    if cached is not None:
        return cached

    latest = Article.objects.aggregate(latest=Max("added_at"))["latest"]
    value = latest.isoformat() if latest else None
    cache.set(LAST_UPDATE_CACHE_KEY, value, LAST_UPDATE_CACHE_SECONDS)
    return value


@require_http_methods(["GET"])
def article(request: HttpRequest, pk: int) -> HttpResponse:
    return render(
        request,
        "tech/article.html",
        {"article": get_object_or_404(Article.objects.select_related("website", "author"), pk=pk)},
    )


@staff_member_required
@require_http_methods(["GET", "POST"])
def importform(request: HttpRequest) -> HttpResponse:
    """Run an importer on demand. Staff only: it makes outbound requests and writes rows."""
    result = None
    form = ImportForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        importer = load_importer(form.cleaned_data["importer_type"])
        result = importer.do_import(days=form.cleaned_data["num_of_days"]).as_dict()

    return render(request, "tech/importform.html", {"form": form, "result": result})
