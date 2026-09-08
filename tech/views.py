from __future__ import annotations

import datetime

from django.contrib.admin.views.decorators import staff_member_required
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
MAX_OFFSET = 100_000


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
        requested_offset = _int_param(request, "offset", 0)
        days_future = _int_param(request, "days_future", None)
        days_past = _int_param(request, "days_past", None)
    except BadParameter as exc:
        return HttpResponseBadRequest(str(exc))

    limit = max(1, min(requested_limit or DEFAULT_LIMIT, MAX_LIMIT))
    offset = max(0, min(requested_offset or 0, MAX_OFFSET))
    queryset = Article.objects.select_related("website", "author")

    sort_by = request.GET.get("sort_by")
    if sort_by is not None:
        if sort_by not in SORTABLE_FIELDS:
            return HttpResponseBadRequest(
                "sort_by must be one of: " + ", ".join(sorted(SORTABLE_FIELDS))
            )
        queryset = queryset.order_by(sort_by)

    # Both windows are measured from the start of today, so this morning's
    # articles count either way. days_future is inherited from the events domain
    # this began in, where "what is coming up" is the natural question; for a
    # news feed days_past is usually the one you want.
    midnight = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    if days_future is not None:
        queryset = queryset.filter(
            time__gte=midnight, time__lte=midnight + datetime.timedelta(days=days_future)
        )
    if days_past is not None:
        queryset = queryset.filter(
            time__gte=midnight - datetime.timedelta(days=days_past),
            time__lte=midnight + datetime.timedelta(days=1),
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
        for article in queryset[offset : offset + limit]
    ]
    return JsonResponse(
        {"count": len(payload), "offset": offset, "limit": limit, "results": payload}
    )


def _last_update() -> str | None:
    """The newest added_at, asked of the database every time.

    The 2013 version wrote this to a file and refreshed it every two hours,
    which meant the endpoint whose entire job is saying "here is when the data
    last changed" could be two hours wrong. added_at is indexed, so a single
    aggregate is cheaper than the cache was worth.
    """
    latest = Article.objects.aggregate(latest=Max("added_at"))["latest"]
    return latest.isoformat() if latest else None


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
