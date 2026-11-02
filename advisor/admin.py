from django.contrib import admin

from .models import ChatMessage, ChatUsage


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ["plant", "owner", "role", "is_error", "created_at"]
    list_filter = ["role", "is_error"]
    readonly_fields = ["owner", "plant", "role", "content", "is_error", "created_at"]

    def has_add_permission(self, request):
        return False


@admin.register(ChatUsage)
class ChatUsageAdmin(admin.ModelAdmin):
    list_display = ["owner", "date", "count"]
    readonly_fields = ["owner", "date", "count"]

    def has_add_permission(self, request):
        return False
