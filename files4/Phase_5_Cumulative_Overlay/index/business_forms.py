"""Consumer form for the normalized database (Phase 5, Slice 1).

Same fields, labels, widgets and validation as index.forms.ConsumerForm, so the existing template renders
unchanged. Dropdown values stay the legacy ids (barangay), codes (consumer type, penalty), so posted values
mean the same thing. The form is a plain Form: a ModelForm on the legacy model would try to assign normalized
objects to legacy foreign keys.
"""

from django import forms

from wb_core.models import Barangay, ConsumerType, PenaltyCode


class BarangayChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.name


class ConsumerTypeChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.name


class PenaltyChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.penalty_code


class NormalizedConsumerForm(forms.Form):
    CHOICES = (("MALE", "MALE"), ("FEMALE", "FEMALE"))

    firstname = forms.CharField(widget=forms.TextInput(attrs={"class": "form-control"}))
    middlename = forms.CharField(widget=forms.TextInput(attrs={"class": "form-control"}), required=False)
    lastname = forms.CharField(widget=forms.TextInput(attrs={"class": "form-control"}))
    mobilenum = forms.CharField(
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "09XXXXXXXXX",
                                      "onkeypress": "return onlyNumberKey(event)", "maxlength": "11"}),
        required=False)
    email = forms.EmailField(widget=forms.EmailInput(attrs={"class": "form-control"}), required=False)
    sex = forms.ChoiceField(widget=forms.Select(attrs={"class": "form-select input-group"}), choices=CHOICES)
    sitio = forms.CharField(widget=forms.TextInput(attrs={"class": "form-control"}), required=False)
    homeaddress = forms.CharField(widget=forms.TextInput(attrs={"class": "form-control"}))
    meternumber = forms.CharField(widget=forms.TextInput(attrs={"class": "form-control"}))
    initialmeterreading = forms.IntegerField(widget=forms.NumberInput(attrs={"class": "form-control", "min": 0}))
    installation_address = BarangayChoiceField(
        widget=forms.Select(attrs={"class": "form-select input-group"}),
        queryset=Barangay.objects.using("normalized").order_by("pk"), to_field_name="legacy_barangay_id")
    contypeid = ConsumerTypeChoiceField(
        widget=forms.Select(attrs={"class": "form-select input-group"}),
        queryset=ConsumerType.objects.using("normalized").order_by("pk"), to_field_name="consumer_type_code")
    penaltycode = PenaltyChoiceField(
        widget=forms.Select(attrs={"class": "form-select input-group"}),
        queryset=PenaltyCode.objects.using("normalized").order_by("pk"), to_field_name="penalty_code", required=False)
    birthdate = forms.DateField(widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}), required=False)
