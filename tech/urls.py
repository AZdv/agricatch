from django.urls import path

from tech import views

app_name = "tech"

urlpatterns = [
    path("articles", views.articles, name="articles"),
    path("article/<int:pk>", views.article, name="article"),
    path("importform", views.importform, name="importform"),
]
