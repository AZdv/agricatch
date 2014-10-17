from django.shortcuts import render
from django.http import HttpResponseRedirect, HttpResponseNotFound
from django.views.decorators.http import require_http_methods
from tech.models import Article, Website
import tech.forms as forms
from django.core import serializers
from pprint import pformat
#import tech.tasks
from django.http import HttpResponse
import datetime
from tech.helpers.encoders import CustomJSONEncoder
from tech.helpers import viewhelper as helper 
import os


def json_view(func):
    def wrapper(*args, **kwargs):
        import simplejson
        result = func(*args, **kwargs)
        if type(result) is str:
            result = simplejson.dumps(result)
        else:
            result = simplejson.dumps(list(result),cls=CustomJSONEncoder)
        return HttpResponse(result,mimetype="application/json")
    return wrapper

@json_view
def articles(request, *args, **kwargs):
    if 'last_update' in request.GET:
        file_path = 'assets/'
        last_update_file = 'last_update.txt'
        result = helper.get_last_update(os.path.dirname(__file__)+'/'+file_path,last_update_file)

        return result
    else:
        from models import Article
        result = Article.objects.all()
        extra_args = dict()
    
        if 'sort_by' in request.GET:
            result = result.order_by(request.GET['sort_by'])

        if 'days_future' in request.GET:
            last_day = datetime.date.today() + datetime.timedelta(days=int(request.GET['days_future']))
            result = result.filter(time__gte=datetime.date.today(),time__lte=last_day) #great/equal to today, less/equal to today+days_future

        if extra_args:
            result = result.extra(**extra_args)
            result = result.select_related()
        return result

def article(request, num):
    chosen_article = Article.objects.get(pk=num)
    return render(request,'article.html', {'chosen_article' : chosen_article})
    

def importform(request):
    if request.META['REMOTE_ADDR'] == '127.0.0.1' and request.META['SERVER_NAME'] == 'localhost': #import only from local! (testing)
        if request.method == 'POST':
            form = forms.ImportForm(request.POST)
            if form.is_valid():
                importer_type = str(form.cleaned_data['importer_type']) #e.g. kidsil
                num_of_days = int(form.cleaned_data['num_of_days']) #e.g. 1-10
                if not num_of_days:
                    num_of_days = 1

                class_name = importer_type.title()  #e,g, Kidsil
                importer_class = __import__(name='tech.websites', fromlist=[importer_type]) # = i.e. from tech.websites import kidsil as importer_class 
                importer_class = getattr(importer_class,importer_type) # = kidsil.Kidsil
                importer_class = getattr(importer_class,class_name)() # = Kidsil()
                
                import_result = importer_class.do_import(num_of_days)
                failed_objects = int(import_result['failed_objects'])
                successful_objects = int(import_result['total_objects']) - int(import_result['failed_objects'])
    
                response = True
                
                return render(request, 'importform.html', {
                                    'form' : form,
                                    'importer_type' : importer_type,
                                    'num_of_days' : num_of_days, 
                                    'failed_objects' : failed_objects, 
                                    'successful_objects' : successful_objects, 
                                    'response' : response
                })
    
            
        else:
            form = forms.ImportForm()
            
        return render(request, 'importform.html', {'form' : form})
    
    else:
        return HttpResponseNotFound('<h1>Page not found</h1>')
