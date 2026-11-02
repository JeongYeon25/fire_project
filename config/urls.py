from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from plants.views import root

urlpatterns = [
    path("", root, name="root"),
    path("admin/", admin.site.urls),
    path("", include("accounts.urls")),
    path("", include("plants.urls")),
    path("", include("diary.urls")),
    path("", include("alerts.urls")),
    path("", include("advisor.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
