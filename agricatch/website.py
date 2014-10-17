import agricatch.helpers.importhelper as helper
from  agricatch.helpers.general import isstr
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.conf import settings
import importlib
import os, sys

models = importlib.import_module(settings.APP_NAME + '.models') # = e.g. import tech.models as models

from pprint import pprint,pformat
import warnings, celery, logging
import logging
import datetime
from dateutil.parser import parse as t_parse

"""
Generic Website Class, this is a Base class from which every Website should inherit.

Written By: Asaf Zamir
more info: www.github.com/AZdv

Attributes:
 @var string website - the slug of the Website connected to this importer (each importer MUST have a Website Slug)
 @var string type - the slug of the Website connected to this importer (each importer MUST have a Website Slug)
 @var Dictionary url_info - @elem string url - the address  with %TIME% to symbolized the place where the time variable should go (e.g. http://www.google.com/%TIME%),
    @elem string time_structure - Time structure (e.g. mm-dd-yyyy) inside the URL part
    @elem integer days_on_page - Number of days in each page (some indexes show a whole week on one page)
    @elem Array pagination (optional) - in case of pagination, the array will hold the Xpath for getting pages, whereas %PAGE_NUM% will be replaced with the page number
    @elem Boolean ignore_time (optional) - in case there's no way to insert time (i.e. an RSS feed), importing only once.

 @var Dictionary structure - the Structure for retrieving the Xpath & general location information for each field
    @elem child_xpath - the Xpath to the object (e.g. event) (a selector that includes all objects, so it can be iterated)
    @elem object_url (optional) - if all of the object fields are under a URL, we save extra calls by getting the DOM of this url once and getting the elements inside, instead of calling the url on each field
    @elem fields (key is field name) - an Array that consists of the elements to be retrieved - "name" field is REQUIRED.
       @elem type - Type of extraction normal (default, grab text), time (format to timestamp, extra 'format' parameter with optional %TIME% to add current date), boolean (get boolean..), table (in case the field is a foreign key, contains an array of 'fields' for the table)
       @elem xpath - the xpath to the field, if type=group the xpath points to the url to grab the extra information from
       @elem url (optional) - in case the information is in an external url, the xpath will be searched inside the url's contents
       @elem url_no_href (optional) - in case the url is inside the field, and not in the "href" attribute (usually the case on RSS)
       @elem json_select (optional) - in case the data is inside a JSON object (happens on REST APIs), the path to the data itself within JSON (format field->field->field)
       @elem fields (on type:table) - in case type = table (another DB table), the extra fields to be retrieved (xpath and types) 
       @elem function (optional) - run an extra function on the field, this names the function
       @elem format (on type:time) - specific format for time, %STR% is the string, %TIME% can also be used (the current date) in case it's not in the field
       @elem remove (on type:time) - remove extra stuff from the time, in case it helps to strtotime it

"""
class Website:
    website = None
    structure = {}
    url_info = {}
    time_param = None
    dom = None
    dom_inner = None
    total_objects = 0
    failed_objects = 0
    type = None
    debug = False
    default_required = True #default field behavior is required
    on_field_failed = 'continue' #what to do when a required field wasn't found, continue or break
    current_url = None #current url being crawled, mainly for debugging & logging
    article_counter = False #enabled in case child_xpath doesn't exist, have to count by title

    def __init__(self):
        self.website = self.__class__.__name__.lower()

    def do_import(self,num_of_days=7,start_day=datetime.date.today(),url_param=None):
        """
         This is where the real magic happens.
         We go through the url_info array first, to find out the url we need to grab from at the start
         (as well as how many in case of pagination / insufficient events in specific url).
         Then we go through structure to grab the structure of the page (XPATH to locate event details)
        """
        self.logger = logging.getLogger('agricatch')
        days_on_page = 1
        days_counter = 0
        if 'days_on_page' in self.url_info:
            days_on_page = self.url_info['days_on_page']

        while days_counter <= num_of_days:
            #for days_counter in range(0,num_of_days):
            if not url_param:
                url = self.url_info['url']
                if ('ignore_time' not in self.url_info):
                    #this is what usually happens
                    calculated_time = start_day + datetime.timedelta(days=days_counter)
                    self.time_param = calculated_time.strftime('%d-%m-%Y')  #time_param is for internal use  no need for changing formats.

                    #looking for %m or %d or %Y
                    url = helper.replace_parameters(url,calculated_time)
            else:
                url = url_param
                self.debug = True




            self.current_url = url
            self.create_dom(url)

            if 'pagination' in self.structure:
                pagination = self.structure['pagination']
                pagination_elements = self.dom.xpath(pagination)
            else:
                pagination_elements = [1]


            for page_link in pagination_elements:
                #self.create_dom(url) #why is this here (taken from an older version) ??
                if ((pagination_elements != [1]) and (pagination_elements.index(page_link) > 0)):
                    pag_url = page_link.get('href')

                    if pag_url:
                        self.current_url = pag_url
                        self.create_dom(pag_url)
                    else:
                        break

                articles = False
                if self.structure.get('child_xpath'):
                    articles = self.dom.xpath(self.structure.get('child_xpath'))
                    article_count = len(articles)
                else:
                    article_count = len(self.dom.xpath(self.structure['fields']['name']['xpath']))

                for article_counter in xrange(0,article_count):
                    if articles:
                        article = articles[article_counter]
                    else:
                        self.article_counter = article_counter
                        article = False
                    if 'object_url' in self.structure:
                        object_url = self.extract_xpath(self.dom,articles[article_counter],self.structure['object_url'])

                        if not object_url:
                            error_string = """object_url didn\'t return an article! \n
                                              xpath: {0} \n
                                              website url: {1}""".format(self.structure['object_url'],url)
                            raise Exception(error_string)

                        self.current_url = object_url
                        self.create_dom(object_url, 'dom_event')
                        object_url_object = self.dom_event.xpath(self.structure['object_url_child_xpath'])
                        if type(object_url_object) is list:
                            object_url_object = object_url_object[0]

                        saved_object = self.object_write(object_url_object, self.type, None, 'dom_event')
                    else:
                        if type(article) is list:
                            article = article[0]
                        saved_object = self.object_write(article, self.type)

                    if saved_object == False: #required field wasn't found, error logged, skipping.
                        self.failed_objects += 1
                        if self.on_field_failed == 'continue':
                            continue
                        else:
                            break

                    if hasattr(saved_object,'website') or hasattr(saved_object,'website_id'):
                        website_object, result = models.Website.objects.get_or_create(slug=self.website)
                        saved_object.website = website_object

                    try:
                        if hasattr(self,'prepare_before_save'):
                            saved_object = self.prepare_before_save(saved_object)
                        saved_object.save()
                        self.total_objects += 1
                    except (ValidationError, IntegrityError) as e:
                        print pprint(e)
                    except Warning:
                        print 'Warning of some sorts...'


            days_counter += days_on_page
            #ignore_time makes importing happen only once
            if ('ignore_time' in self.url_info and self.urlinfo['ignore_time']):
                break



            #end-of-while
        return {'total_objects' : self.total_objects, 'failed_objects' : self.failed_objects }


    def create_dom(self,url,dom_name = 'dom'):
        import urllib2
        from lxml.html import parse
        from lxml import etree

        #Registering XPath functions (from importhelper)
        ns = etree.FunctionNamespace(None)
        for helper_func in dir(helper):
            func_prefix = 'xpath_func_'
            if helper_func.startswith(func_prefix):
                ns[helper_func[len(func_prefix):]] = getattr(helper,helper_func)  #function's name is defined without the prefix



        if not self.debug:
            url = helper.relative_url_to_absolute(url,self.url_info['url'])

        try:
            response = urllib2.urlopen(url)
        except urllib2.URLError, e:
            print 'URL is unavailable! :( \n url: {0} \n details: {1}'.format(url,pprint(e.args))
            return False

        tree = parse(response)

        #tree.xpath('body')
        setattr(self,dom_name,tree)

    def object_write(self, search_object, object_type, fields = None, dom = 'dom'):
        db_object = getattr(models,object_type)()
        if not fields:
            fields = self.structure['fields']

        skip_importing = False
        for (key, field) in fields.iteritems():
            if 'url' in field:
                #in some cases, the field information is inside another page, so we need to grab it. (no need for url_no_href and such, should be defined inside xpath)
                url = self.extract_xpath(dom, search_object, field['url'])
                dom = 'dom_url'

                #on table fields, we're keeping the dom_inner for the sub_fields
                if field['type'] == 'table':
                    dom = 'dom_inner'

                self.current_url = url
                self.create_dom(url, dom)

            elif dom == 'dom_url':
                dom = 'dom'

            if 'url' in field:
                set_value = self.extract_xpath(dom, None, field)
            else:
                set_value = self.extract_xpath(dom, search_object, field)

            if self.default_required or 'required' in field:
                if set_value == False:
                    skip_importing = True
                    break

            if isstr(field) or field['type'] == 'normal':
                setattr(db_object,key,set_value)
            elif field['type'] == 'time':
                time_str = field['format'].replace('%TIME%',self.time_param).replace('%STR%',set_value)
                if 'remove' in field:
                    for remove_me in field['remove']:
                        time_str = time_str.replace(remove_me,'')

                try:
                    time_str_old = time_str
                    time_str = datetime.datetime.strftime(t_parse(time_str),'%Y-%m-%d %H:%M:%S') #MySQL timestamp format
                except ValueError:
                    return 'unknown string format!'

                setattr(db_object,key,time_str)
            elif field['type'] == 'table':

                related_name = db_object.get_name_by_relation_field(key) #e.g. Place
                if 'url' in field:
                    related_object = getattr(self, dom).xpath(field['child_xpath'])
                else:
                    related_object = search_object.xpath(field['child_xpath'])
                if type(related_object) is list:
                    related_object = related_object[0]

                self.inside_related_object = True
                related_object = self.object_write(related_object, related_name, field['fields'], dom)

                if related_object == False: #some inside fields weren't found
                    skip_importing = True


                self.inside_related_object = False

                try:
                    the_id = related_object.save()
                    if the_id:
                        related_object.id = the_id
                except (ValidationError, IntegrityError) as e:
                    print 'Error on Related Object: ' + related_name + '\n' + pformat(e)
                    break

                setattr(db_object,key,related_object) #saving related object (e.g. Place) into main object (e.g. Event) as a reference
        if skip_importing:
            return False

        return db_object

    def extract_xpath(self,dom, search_object,field):
        """
        simply extracting text only via xpath
        @param search_object the object from which we extract the text
        @param field the xpath, if it's an array, we get the $xpath['xpath'] and look for $xpath['function'] in case an extra function should be used on the data extracted
        @return string
        """
        xpath = field
        if type(field) in [list,dict]:
            xpath = field['xpath']
        if self.article_counter is not False:
            xpath = '(' + xpath + ')[' + str(self.article_counter + 1) + ']'
        try:
            if search_object is not None:
                if type(search_object) is list:
                    search_object = search_object[0]

                result = search_object.xpath(xpath)
            else:
                result = getattr(self,dom).xpath(xpath)
        except AttributeError:
            print 'xpath object doesn\'t fit:' + pformat(xpath)
            print '\nsearch_object: ' + pformat(search_object)
            print '\nfield: ' + pformat(field)
            import sys
            sys.exit()

        if type(result) is list:
            try:
                result = result[0]
            except IndexError:
                from lxml.etree import tostring
                debug_msg = str(datetime.datetime.today().strftime('%Y-%m-%d %H:%M:%S'))
                debug_msg += '\nresult is empty? ' + pformat(result)
                debug_msg += '\nsearch_object: ' + tostring(search_object)
                debug_msg += '\nfield: ' + pformat(field)
                debug_msg += '\nurl: ' + self.current_url
                debug_msg += '\n\n\n'
                self.logger.debug(debug_msg)

                return False


        if not isinstance(result,str):
            try:
                result = result.text_content()
            except AttributeError:
                result.encode('utf-8') #result is already ready 

        params = None
        if 'function_parameters' in field:
            params = field['function_parameters']
            for param in params:
                params[param] = params[param].replace('%TIME%',self.time_param)
                
        if (type(field) is dict) and ('function' in field):
            try:
                result = getattr(helper, field['function'])(result,params)
            except Exception as e:
                print 'Error while trying to run a function: ' + field['function']
        
        result = result.strip('/\-_ \t\n\r')

        return result
        
        