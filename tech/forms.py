from __future__ import annotations

from typing import Any, cast

from django import forms

from agricatch.helpers.general import get_importer_choices

MAX_DAYS = 10


class ImportForm(forms.Form):
    importer_type = forms.ChoiceField(choices=())
    num_of_days = forms.IntegerField(min_value=1, max_value=MAX_DAYS, initial=1)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Resolved per-instance so a newly added importer shows up without a restart.
        field = cast(forms.ChoiceField, self.fields["importer_type"])
        field.choices = get_importer_choices()
