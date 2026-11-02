from django.urls import path

from . import views

app_name = "advisor"

urlpatterns = [
    path("plants/<int:pk>/chat/", views.chat_ask, name="ask"),
    path("plants/<int:pk>/chat/history/", views.chat_history, name="history"),
    path("plants/<int:pk>/chat/clear/", views.chat_clear, name="clear"),
]
