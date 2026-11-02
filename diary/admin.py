from django.contrib import admin

from .models import DiaryEntry


@admin.register(DiaryEntry)
class DiaryEntryAdmin(admin.ModelAdmin):
    list_display = ["owner", "plant", "is_auto", "created_at"]
    list_filter = ["owner", "is_auto"]
