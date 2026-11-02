from django import forms
from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse

from accounts.decorators import app_view
from plants.views import my_plants

from .models import DiaryEntry


class DiaryForm(forms.ModelForm):
    class Meta:
        model = DiaryEntry
        fields = ["plant", "content"]
        widgets = {"content": forms.Textarea(attrs={"rows": 6, "maxlength": 1000, "placeholder": "오늘 식물은 어땠나요?"})}

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["plant"].queryset = my_plants(owner)
        self.fields["plant"].required = False
        self.fields["plant"].empty_label = "화분 전체"
        self.fields["plant"].label_from_instance = lambda p: p.title
        self.fields["plant"].label = "화분"


@app_view
def diary(request):
    """나만 보는 식물 일기."""
    slot = request.GET.get("plant", "")
    if request.method == "POST":
        form = DiaryForm(request.POST, owner=request.user)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.owner = request.user
            entry.save()
            messages.success(request, "다이어리에 남겼어요.")
            suffix = f"?plant={entry.plant.slot}" if entry.plant else ""
            return redirect(reverse("diary:index") + suffix)
    else:
        initial = {}
        write = request.GET.get("write", "")
        selected = my_plants(request.user).filter(pk=write).first() if write.isdigit() else None
        if selected:
            initial["plant"] = selected
        form = DiaryForm(initial=initial, owner=request.user)

    entries = DiaryEntry.objects.filter(owner=request.user).select_related("plant")
    if slot:
        entries = entries.filter(plant__slot=slot)
    context = {
        "form": form,
        "entries": entries[:60],
        "plants": my_plants(request.user),
        "slot": slot,
        "nav": "diary",
    }
    return render(request, "diary/diary.html", context)
