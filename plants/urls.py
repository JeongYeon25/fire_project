from django.urls import path

from . import api, device_views, task_views, views

app_name = "plants"

urlpatterns = [
    path("home/", views.home, name="home"),
    path("plants/", views.plant_list, name="list"),
    path("plants/add/", views.plant_add, name="add"),
    path("plants/<int:pk>/panel/", views.plant_panel, name="panel"),
    path("plants/<int:pk>/edit/", views.plant_edit, name="edit"),
    path("plants/<int:pk>/key/", views.plant_key, name="key"),
    path("plants/<int:pk>/key/reissue/", views.plant_key_reissue, name="key_reissue"),
    path("tasks/", task_views.tasks_page, name="tasks"),
    path("tasks/add/", task_views.task_add, name="task_add"),
    path("tasks/<int:pk>/panel/", task_views.task_panel, name="task_panel"),
    path("tasks/<int:pk>/edit/", task_views.task_edit, name="task_edit"),
    path("tasks/<int:pk>/delete/", task_views.task_delete, name="task_delete"),
    path("tasks/<int:pk>/today/", task_views.task_move_today, name="task_today"),
    path("api/tasks/<int:pk>/check/", task_views.task_check, name="task_check"),
    path("devices/", device_views.devices, name="devices"),
    path("devices/add/", device_views.device_add, name="device_add"),
    path("devices/<int:pk>/", device_views.device_detail, name="device"),
    path("devices/<int:pk>/channels/", device_views.device_channels, name="device_channels"),
    path("devices/<int:pk>/key/reissue/", device_views.device_key_reissue, name="device_key_reissue"),
    path("devices/<int:pk>/archive/", device_views.device_archive, name="device_archive"),
    path("graph/", views.graph, name="graph"),
    path("photos/", views.photos, name="photos"),
    path("photos/upload/", views.photo_upload, name="photo_upload"),
    path("photos/<int:pk>/panel/", views.photo_panel, name="photo_panel"),
    path("photos/<int:pk>/delete/", views.photo_delete, name="photo_delete"),
    path("api/graph/", api.graph_data, name="graph_data"),
    # 라즈베리파이는 슬래시 없이 보낸다. POST는 APPEND_SLASH 리다이렉트를 거치면 본문이 사라지므로 둘 다 직접 받는다.
    path("api/readings/", api.receive_reading, name="readings"),
    path("api/readings", api.receive_reading),
    path("health", api.health, name="health"),
    path("health/", api.health),
    path("api/todo/", api.todo_check, name="todo"),
]
