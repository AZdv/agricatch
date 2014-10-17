from django.core.management.base import BaseCommand, CommandError
from agricatch.helpers.general import get_all_importers
from optparse import make_option
import logging
from pprint import pprint, pformat
from django.conf import settings
import datetime

class Command(BaseCommand):
    option_list = BaseCommand.option_list + (
        make_option('-d', '--days', action='store', dest='days', default='7',
        type='int'),
    )
    args = '<import_name ...>'
    help = 'Imports objects from a specific website, if none is mentioned, imports all\n'
    help = help + 'example command: ./manage.py doimport website_name --days=7'
    
    def handle(self,*args, **options):
        importers = args
        logger = logging.getLogger('doimport')
        
        if 'days' not in options:
            options['days'] = 7
        options['days'] = int(options['days'])

        if not importers:
            importers = get_all_importers(app_name=settings.APP_NAME)
            
        for importer_type in importers:
            class_name = importer_type.title()  #e,g, Kidsil
            importer_class = __import__(name=settings.APP_NAME + '.websites', fromlist=[importer_type]) # = from tech.websites import website_name as importer_class 
            importer_class = getattr(importer_class,importer_type) # = website_name.WebsiteClass
            importer_class = getattr(importer_class,class_name)() # = WebsiteClass()
            print 'Importing from ' + class_name
            
            counter , current_days = 0 , 0
            start_day = datetime.date.today()
            end_day = start_day
            last_import_day = start_day + datetime.timedelta(days=options['days'])
            result = importer_class.do_import(options['days'])
            pprint(result)