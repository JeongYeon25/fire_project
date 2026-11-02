"""화분 이름·등록·수정 폼. 이름 규칙(앞뒤 공백 제거 후 1~12자)은 여기 한 곳에서 검사한다."""

from django import forms

from .models import DEVICE_NAME_MAX, PLANT_NAME_MAX, TASK_TITLE_MAX, DeviceChannel, Plant, Task, selectable_crops
from .text import josa

NAME_REQUIRED = "이름을 지어 주세요."
NAME_TOO_LONG = f"이름은 {PLANT_NAME_MAX}자까지 지을 수 있어요."


def clean_plant_name(value):
    name = (value or "").strip()
    if not name:
        raise forms.ValidationError(NAME_REQUIRED)
    if len(name) > PLANT_NAME_MAX:
        raise forms.ValidationError(NAME_TOO_LONG)
    return name


class PlantNameField(forms.CharField):
    def __init__(self, **kwargs):
        kwargs.setdefault("label", "이름")
        kwargs.setdefault("strip", True)
        super().__init__(required=False, **kwargs)
        self.widget.attrs.update({"maxlength": PLANT_NAME_MAX, "autocomplete": "off"})

    def clean(self, value):
        return clean_plant_name(super().clean(value))


class PlantNameForm(forms.Form):
    """온보딩 3단계 '이름 지어 주세요'."""

    name = PlantNameField()


class PlantAddForm(forms.ModelForm):
    name = PlantNameField()

    class Meta:
        model = Plant
        fields = ["name", "crop", "condition"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["crop"].queryset = selectable_crops()

    def clean_condition(self):
        return self.cleaned_data["condition"].strip()


class PlantEditForm(forms.ModelForm):
    """상세 팝업 '작물 바꾸기 / 이름 바꾸기'. 선택 목록에서 빠진 작물(고추·대파) 화분도 지금 작물 그대로 저장할 수 있다."""

    name = PlantNameField()

    class Meta:
        model = Plant
        fields = ["name", "crop", "condition"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["crop"].queryset = selectable_crops(include=self.instance.crop_id)

    def clean_condition(self):
        return self.cleaned_data["condition"].strip()


class TaskForm(forms.ModelForm):
    """할 일 추가·수정. 날짜나 시각을 바꾸면 알림 보낸 기록(notified_at)을 비워 다시 알림 대상이 되게 한다."""

    class Meta:
        model = Task
        fields = ["title", "due_date", "due_time", "plant", "notify"]
        widgets = {
            "due_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "due_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        }
        error_messages = {
            "title": {"required": "할 일을 적어 주세요.", "max_length": f"할 일은 {TASK_TITLE_MAX}자까지 적을 수 있어요."},
            "due_date": {"required": "날짜를 골라 주세요.", "invalid": "날짜를 다시 골라 주세요."},
            "due_time": {"invalid": "시각을 다시 골라 주세요."},
        }

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["plant"].queryset = Plant.objects.filter(owner=owner)
        self.fields["plant"].required = False
        self.fields["plant"].empty_label = "화분 없음"
        self.fields["plant"].label_from_instance = lambda p: p.title
        self.fields["title"].widget.attrs.update({"maxlength": TASK_TITLE_MAX, "autocomplete": "off"})
        self.fields["due_date"].input_formats = ["%Y-%m-%d"]
        self.fields["due_time"].input_formats = ["%H:%M", "%H:%M:%S"]

    def clean_title(self):
        title = (self.cleaned_data.get("title") or "").strip()
        if not title:
            raise forms.ValidationError("할 일을 적어 주세요.")
        return title

    def save(self, commit=True):
        task = super().save(commit=False)
        if task.pk and ("due_date" in self.changed_data or "due_time" in self.changed_data):
            task.notified_at = None
        if commit:
            task.save()
        return task


class DeviceAddForm(forms.Form):
    """내 기기 등록: 이름만 받는다(앞뒤 공백 제거 후 1~20자). 기기 ID와 키는 서버가 만든다."""

    name = forms.CharField(label="기기 이름", required=False, strip=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].widget.attrs.update({"maxlength": DEVICE_NAME_MAX, "autocomplete": "off"})

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            raise forms.ValidationError("기기 이름을 적어 주세요.")
        if len(name) > DEVICE_NAME_MAX:
            raise forms.ValidationError(f"기기 이름은 {DEVICE_NAME_MAX}자까지 적을 수 있어요.")
        return name


class DeviceChannelForm(forms.Form):
    """채널 soil1~4 ↔ 내 화분. 선택지는 내 화분만(다른 사람 화분은 보이지도, 골라지지도 않는다).
    한 화분은 한 채널에만: 이 기기 안에서 겹치거나 내 다른 기기에 이미 연결돼 있으면 막는다. 이 기기 안에서 맞바꾸기는 된다."""

    def __init__(self, *args, device, **kwargs):
        super().__init__(*args, **kwargs)
        self.device = device
        current = dict(DeviceChannel.objects.filter(device=device).values_list("channel", "plant_id"))
        plants = Plant.objects.filter(owner=device.owner).select_related("crop")
        for channel, label in DeviceChannel.CHANNELS:
            field = forms.ModelChoiceField(
                queryset=plants, required=False, empty_label="연결 안 함", label=label, initial=current.get(channel)
            )
            field.label_from_instance = lambda p: f"{p.title} · {p.slot_label}" if p.name else p.slot_label
            self.fields[f"ch{channel}"] = field

    def clean(self):
        cleaned = super().clean()
        seen = {}
        for channel, label in DeviceChannel.CHANNELS:
            plant = cleaned.get(f"ch{channel}")
            if plant is None:
                continue
            if plant.pk in seen:
                raise forms.ValidationError(
                    f"{josa(plant.title, '은', '는')} {seen[plant.pk]}와 {label}에 함께 연결할 수 없어요. 한 화분은 한 채널에만 연결해요."
                )
            seen[plant.pk] = label
            other = DeviceChannel.objects.filter(plant=plant).exclude(device=self.device).select_related("device").first()
            if other is not None:
                raise forms.ValidationError(
                    f"{josa(plant.title, '은', '는')} 이미 {other.device.title}의 {other.get_channel_display()}에 연결돼 있어요."
                )
        return cleaned

    def save(self):
        """연결을 저장한다. 바뀐 게 있으면 True."""
        changed = False
        for channel, _ in DeviceChannel.CHANNELS:
            plant = self.cleaned_data.get(f"ch{channel}")
            link, _ = DeviceChannel.objects.get_or_create(device=self.device, channel=channel)
            if link.plant_id != (plant.pk if plant else None):
                link.plant = plant
                link.save(update_fields=["plant"])
                changed = True
        return changed


def first_error(form):
    for errors in form.errors.values():
        if errors:
            return errors[0]
    return ""
