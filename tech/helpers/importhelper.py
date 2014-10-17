# -*- coding: utf-8 -*-
def replace_all(text, dic):
    for replace_with, replace_what in dic.iteritems():
        if type(replace_what) is list:
            for letter in replace_what:
                text = text.replace(letter,replace_with)
        else:
            text = text.replace(replace_what, str(replace_with))
    return text
def slugify(string,params = [],extra_clean = True):
    import re
    #unescape html entity signs (e.g. &amp; -> &) & lowercase string
    import HTMLParser 
    string = HTMLParser.HTMLParser().unescape(string).lower()
    translation_dic = {
           'ae' : ['Ä','ä','&Auml;','&auml;'],
           'oe' : ['Ö','ö','&Ouml;','&ouml;'],
           'ue' : ['Ü','ü','&Uuml;','&uuml;'],
           'ss' : ['ß','&szlig;'],
    }
    string = replace_all(string.encode('utf-8'),translation_dic)
    if extra_clean:
        string = re.sub(r'[^a-zA-Z0-9\_\-\s]','',string)
        string = re.sub(r'[\s]{2,}',' ',string)
        string = string.replace(' ','-').replace('_','-').strip(' -')
        string = re.sub(r'[\-]{2,}','-',string)
    
    return string

    
def remove_time_end(string, params=[]):
    import re
    from datetime import date,datetime
    calculated_time = date.today()
    if 'time' in params:
        calculated_time = datetime.strptime(params['time'],'%d-%m-%Y')
    
    #we're getting the year & date currently crawled, in case it's missing from the "time" field, we add them
    current_year = calculated_time.year
    current_date = str(calculated_time.day) + '-' + str(calculated_time.month) #currently not in use 
    
    #cleaning multiple hours
    hours = re.findall(r'\d\d:\d\d',string)
    if len(hours) > 1:
        string = re.sub('-*\s*\d\d:\d\d\s*-*','',string[::-1],len(hours)-1)[::-1] #getting rid of all the duplicate hours except the first one (by reversing string twice)


    match_year = re.findall(r'\d{4}',string)
    if not match_year:
        string = re.sub(r'(.+) (\d\d:\d\d)',r'\1 '+str(current_year)+r' \2',string)    
    
    #cleaning double dates (rare, but happens)
    match_double_dates = re.findall(r'\d\d\.\d\d\.\d\d',string)
    if len(match_double_dates) > 1:
        string = re.sub('-*\s*\d\d\.\d\d\.\d\d\s*-*','',string[::-1],len(match_double_dates)-1)[::-1]
    
    
    string = string.strip()
    
    return string
    
import datetime
def replace_parameters(string,calculated_time=datetime.date.today()):
    parameter_dic = {
            '%d' : str(calculated_time.day).zfill(2), #zfill for leading zero 
            '%m' : str(calculated_time.month).zfill(2), 
            '%Y' : str(calculated_time.year).zfill(2), 
            '%current_d%' : str(datetime.date.today().day).zfill(2),
            '%current_m%' : str(datetime.date.today().month).zfill(2),
            '%current_Y%' : str(datetime.date.today().year).zfill(2),
    }
    for k,v in parameter_dic.iteritems():
        string = string.replace(str(k),str(v))
        
    return string


def relative_url_to_absolute(url,base_url):
    import urlparse

    if ('http' not in url):
        complete_url = urlparse.urlparse(base_url)
        url = complete_url.scheme + '://' + complete_url.netloc + '/' +  url
        
    return url

def dist_calc_mysql_string(long1,lat1,long2='`place`.`longitude`',lat2='`place`.`latitude`',unit='km'):
    radius = 6353 #Earth's radius in Kilometers
    if unit in ['mile','miles']:
        radius = radius * 0.621371192
    string = ('ROUND(' + str(radius) + ' * 2 * ASIN(SQRT( POWER(SIN((' + str(lat2) + ' -'
             'abs( ' + str(lat1) + ')) * pi()/180 / 2),2) + COS(' + str(lat2) + ' * pi()/180 ) * COS( '
             'abs(' + str(lat1) + ') *  pi()/180) * POWER(SIN((' + str(long2) + ' - ' + str(long1) + ') *  pi()/180 / 2), 2) )),2)')
    
    return string

def geocode(location):
    import urllib, simplejson
    from django.conf import settings
    output = "json"
    location = urllib.quote_plus(slugify(location,[],False))
    request = "https://maps.googleapis.com/maps/api/geocode/%s?address=%s&sensor=false" % (output, location)
    data = urllib.urlopen(request).read()
    data = simplejson.loads(data)
    try:
        data = data['results'][0]
    except IndexError:
        return ''

    if 'geometry' in data:
        return data['geometry']['location']




#XPath functions:
def xpath_func_tokenize(context, string, split_token):
    if type(string) is list:
        string = string[0]
    return string.split(split_token)

def xpath_func_findzipcode(context, string):
    import re
    if type(string) is list:
        string = string[0]
    zipcode = re.findall(r'\d{5}',string)
    if zipcode:
        return zipcode
    else:
        return ''
