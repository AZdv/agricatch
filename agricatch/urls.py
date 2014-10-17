from django.conf.urls import patterns, include, url

# Uncomment the next two lines to enable the admin:
from django.contrib import admin
from django.conf import settings

admin.autodiscover() 

urlpatterns = patterns('',
    url(r'^agricatch/', include(settings.APP_NAME + '.urls')),
)