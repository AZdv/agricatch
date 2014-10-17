from django import forms
from agricatch.helpers.general import get_all_importers

class ImportForm(forms.Form):
    module_names = get_all_importers(tuple_form=True)
    max_days = 10

    module_names.append(('celery','Celery - import all using celery (not ready yet)'))
    importer_type = forms.ChoiceField(widget=forms.Select, choices=module_names)
    num_of_days = forms.ChoiceField(widget=forms.Select, choices=[(i, i) for i in range(0,max_days+1)])
    
