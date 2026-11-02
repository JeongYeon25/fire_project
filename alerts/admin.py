from django.contrib import admin

from .models import AlertLog, UserSetting


@admin.register(AlertLog)
class AlertLogAdmin(admin.ModelAdmin):
    list_display = ["plant", "kind", "message", "channel", "sent_at"]
    list_filter = ["kind", "plant__owner"]


admin.site.register(UserSetting)
