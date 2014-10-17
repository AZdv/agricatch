from django.conf.urls import patterns, include, url

urlpatterns = patterns('',
    url(r'^articles$', 'tech.views.articles'),
    url(r'^article/(?P<num>\d+)$', 'tech.views.article'),
    url(r'^importform$', 'tech.views.importform'),
)
