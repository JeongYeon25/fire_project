from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet

from .devices import ArchivedDeviceError, rebuild_device
from .models import Crop, DeviceChannel, DeviceReading, Plant, PlantPhoto, SensorDevice, SensorReading, TodoCheck


@admin.register(Crop)
class CropAdmin(admin.ModelAdmin):
    list_display = ["name", "difficulty", "water_threshold", "light_threshold", "moisture_min", "moisture_max", "temp_min", "temp_max"]


@admin.register(Plant)
class PlantAdmin(admin.ModelAdmin):
    list_display = ["__str__", "owner", "slot", "name", "crop", "condition", "is_demo"]
    list_filter = ["owner", "is_demo"]
    readonly_fields = ["api_key"]


@admin.register(SensorReading)
class SensorReadingAdmin(admin.ModelAdmin):
    list_display = ["plant", "measured_at", "moisture", "light", "temp", "humidity", "device_reading"]
    list_filter = ["plant__owner", "plant__slot"]
    date_hierarchy = "measured_at"
    raw_id_fields = ["device_reading"]


class DeviceChannelFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        seen = {}
        for form in self.forms:
            if not hasattr(form, "cleaned_data") or form.cleaned_data.get("DELETE"):
                continue
            plant = form.cleaned_data.get("plant")
            if plant is None:
                continue
            if plant.pk in seen:
                raise ValidationError(f"{plant}이(가) soil{seen[plant.pk]}와 soil{form.cleaned_data['channel']}에 함께 연결돼 있어요.")
            seen[plant.pk] = form.cleaned_data["channel"]


class DeviceChannelInline(admin.TabularInline):
    model = DeviceChannel
    formset = DeviceChannelFormSet
    extra = 0
    max_num = 4
    raw_id_fields = ["plant"]


@admin.register(SensorDevice)
class SensorDeviceAdmin(admin.ModelAdmin):
    """키 원문은 DB에 없어서 여기에도 나오지 않는다. 해시·앞 6글자는 읽기만. 키 발급·재발급은 내 기기 화면이나 setup_device.
    완전 삭제(원시값·계산한 화분 값까지 함께 지워짐)는 여기서만 한다."""

    list_display = ["device_id", "name", "owner", "last_seen", "reading_count", "key_status", "archived_at"]
    list_filter = ["owner"]
    fields = ["device_id", "name", "owner", "key_status", "key_hash", "key_prefix", "key_issued_at", "last_seen", "archived_at", "reading_count", "created_at"]
    readonly_fields = ["key_status", "key_hash", "key_prefix", "key_issued_at", "last_seen", "archived_at", "reading_count", "created_at"]
    inlines = [DeviceChannelInline]

    @admin.display(description="원시값 행 수")
    def reading_count(self, obj):
        return obj.readings.count() if obj.pk else 0

    @admin.display(description="기기 키")
    def key_status(self, obj):
        if obj.is_archived:
            return "보관함(키 무효)"
        return f"발급됨({obj.key_prefix}…)" if obj.has_key else "없음 — 내 기기 화면에서 발급"

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if any(fs.has_changed() for fs in formsets):
            try:
                made = rebuild_device(form.instance)
            except ArchivedDeviceError as exc:
                self.message_user(request, str(exc), messages.WARNING)
                return
            self.message_user(request, f"채널 연결이 바뀌어 화분 측정값을 다시 계산했어요({made}행).", messages.INFO)


@admin.register(DeviceReading)
class DeviceReadingAdmin(admin.ModelAdmin):
    list_display = ["device", "time", "soil1", "soil2", "soil3", "soil4", "light", "temp", "hum", "n_samples", "note"]
    list_filter = ["device", "note"]
    date_hierarchy = "time"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(PlantPhoto)
class PlantPhotoAdmin(admin.ModelAdmin):
    list_display = ["plant", "taken_at"]
    list_filter = ["plant__owner", "plant__slot"]


admin.site.register(TodoCheck)
