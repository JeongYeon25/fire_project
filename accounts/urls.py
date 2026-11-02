from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("start/", views.onboarding, name="onboarding"),
    path("start/signup/", views.signup, name="signup"),
    path("start/login/", views.login_view, name="login"),
    path("start/crop/", views.choose_crop, name="crop"),
    path("start/name/", views.choose_name, name="name"),
    path("intro/", views.intro, name="intro"),
    path("intro/done/", views.intro_done, name="intro_done"),
    path("logout/", views.logout_view, name="logout"),
]
