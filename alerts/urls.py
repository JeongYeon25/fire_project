from django.urls import path

from . import views

app_name = "alerts"

urlpatterns = [
    path("alerts/", views.settings_page, name="settings"),
    path("api/settings/", views.save_setting, name="save_setting"),
]
