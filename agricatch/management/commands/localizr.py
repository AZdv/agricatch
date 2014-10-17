"""
localizr takes places without long/lat and gets it from the address (hopefully)
run this as a cronjob once a day (should be enough), about one hour after the importing is scheduled
"""

from django.core.management.base import BaseCommand
from optparse import make_option
from django.conf import settings
Place = getattr(__import__(name=settings.APP_NAME + '.models', fromlist='Place'), 'Place')
from django.db.models import Q
import agricatch.helpers.importhelper as helper

class Command(BaseCommand):
    option_list = BaseCommand.option_list + (
        make_option('-l', '--limit', action='store', dest='limit', default='10',
        type='int'),
    )

    def handle(self,*args, **options):
        places_without_location = Place.objects.filter((Q(longitude__isnull=True) | Q(longitude=u'')) & ~Q(raw_address='') & ~Q(raw_address='Unknown'))[:options['limit']]
        for place in places_without_location:
            search_raw_address = place.raw_address
            location_result = helper.geocode(search_raw_address)
            if location_result:
                place.longitude = location_result['lng']
                place.latitude = location_result['lat']
            place.save()