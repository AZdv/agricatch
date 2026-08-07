import datetime

from django.contrib.admin.views.decorators import staff_member_required
from django.core.cache import cache
from django.db.models import Max
from django.http import HttpResponseBadRequest, JsonResponse
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


def _int_param(request, name, default):
    raw = request.GET.get(name)
    if raw is None:
        return default, None
    try:
        return int(raw), None
    except ValueError:
        return None, HttpResponseBadRequest(f"{name} must be an integer")


@require_http_methods(["GET"])
def articles(request):
    if "last_update" in request.GET:
        return JsonResponse({"last_update": _last_update()})

    limit, error = _int_param(request, "limit", DEFAULT_LIMIT)
    if error:
        return error
    limit = max(1, min(limit, MAX_LIMIT))

    queryset = Article.objects.select_related("website")

    sort_by = request.GET.get("sort_by")
    if sort_by is not None:
        if sort_by not in SORTABLE_FIELDS:
            return HttpResponseBadRequest(
                "sort_by must be one of: " + ", ".join(sorted(SORTABLE_FIELDS))
            )
        queryset = queryset.order_by(sort_by)

    days_future, error = _int_param(request, "days_future", None)
    if error:
        return error
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
            "author": article.author,
            "time": article.time.isoformat() if article.time else None,
            "added_at": article.added_at.isoformat(),
            "website": article.website.slug if article.website else None,
        }
        for article in queryset[:limit]
    ]
    return JsonResponse({"count": len(payload), "results": payload})


def _last_update():
    cached = cache.get(LAST_UPDATE_CACHE_KEY)
    if cached is not None:
        return cached

    latest = Article.objects.aggregate(latest=Max("added_at"))["latest"]
    value = latest.isoformat() if latest else None
    cache.set(LAST_UPDATE_CACHE_KEY, value, LAST_UPDATE_CACHE_SECONDS)
    return value


@require_http_methods(["GET"])
def article(request, pk):
    return render(
        request,
        "tech/article.html",
        {"article": get_object_or_404(Article.objects.select_related("website"), pk=pk)},
    )


@staff_member_required
@require_http_methods(["GET", "POST"])
def importform(request):
    """Run an importer on demand. Staff only — it makes outbound requests and writes rows."""
    result = None
    form = ImportForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        importer = load_importer(form.cleaned_data["importer_type"])
        result = importer.do_import(days=form.cleaned_data["num_of_days"]).as_dict()

    return render(request, "tech/importform.html", {"form": form, "result": result})
