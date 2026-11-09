from django.urls import path

from .views import HealthView, TripPlanView

urlpatterns = [
    path("health/", HealthView.as_view()),
    path("plan/", TripPlanView.as_view()),
]
