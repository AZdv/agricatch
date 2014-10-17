import simplejson
import datetime
import pickle

class CustomJSONEncoder(simplejson.JSONEncoder):
    #custom JSONEncoder
    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            return (obj.strftime('%Y-%m-%d %H:%m:%S'))
        
        return simplejson.JSONEncoder.default(self, obj)
        #return {'_python_object': pickle.dumps(obj)}
