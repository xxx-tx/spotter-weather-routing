from django.urls import path
from . import views

urlpatterns = [
    path('health/', views.health_check, name='health'),
    path('trips/validate/', views.validate_trip, name='validate_trip'),
    path('routes/', views.plan_routes, name='plan_rountes'),
]