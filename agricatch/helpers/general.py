import os
from django.conf import settings
def get_all_importers(tuple_form=False, app_name=settings.APP_NAME):
    import os
    ignore_files = ['__init__.py','website.py']
    module_names = []

    (head,tail) = os.path.split(os.path.abspath( __file__ ))
    for r,d,files in os.walk(head + '/../../' + app_name + '/websites/'): #todo: get application name (e.g. tech)
        for file in files:
            if file.endswith('.py') and (file not in ignore_files):
                module_name = file.replace('.py','')
                if tuple_form:
                    module_names.append((module_name,module_name))
                else:
                    module_names.append(module_name)
    return module_names

try:
    basestring  # attempt to evaluate basestring
    def isstr(s):
        return isinstance(s, basestring)
except NameError:
    def isstr(s):
        return isinstance(s, str)