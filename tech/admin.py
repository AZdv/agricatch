from __future__ import annotations

from django.contrib import admin

from tech.models import Article, Author, Website


@admin.register(Website)
class WebsiteAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "address")
    search_fields = ("slug", "name")


@admin.register(Author)
class AuthorAdmin(admin.ModelAdmin):
    list_display = ("name", "article_count")
    search_fields = ("name",)

    @admin.display(description="articles")
    def article_count(self, obj: Author) -> int:
        return int(obj.articles.count())


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("name", "website", "author", "time", "added_at")
    list_filter = ("website", "time")
    search_fields = ("name", "author__name")
    list_select_related = ("website", "author")
    autocomplete_fields = ("author",)
    date_hierarchy = "time"
    readonly_fields = ("content_hash", "added_at")
