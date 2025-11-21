from django.urls import path
from . import views

urlpatterns = [
    path("analyze/", views.analyze_url, name="analyze_url"),
    path("download/", views.download_format, name="download_format"),
]
