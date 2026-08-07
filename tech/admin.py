from django.contrib import admin

from tech.models import Article, Website


@admin.register(Website)
class WebsiteAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "address")
    search_fields = ("slug", "name")


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("name", "website", "author", "time", "added_at")
    list_filter = ("website", "time")
    search_fields = ("name", "author")
    date_hierarchy = "time"
    readonly_fields = ("content_hash", "added_at")
