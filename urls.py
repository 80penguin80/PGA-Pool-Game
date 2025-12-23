from django.urls import path
from . import views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("rules/", views.rules, name="rules"),
    path("tournaments/<int:pk>/", views.tournament_detail, name="tournament_detail"),
    path("tournaments/", views.tournament_list, name="tournament_list"),
    path("tournaments/<int:pk>/pick/", views.make_picks, name="make_picks"),
    path("my-picks/", views.my_picks, name="my_picks"),
    path("standings/", views.standings, name="standings"),
    path("signup/", views.signup, name="signup"),
    path("tournaments/<int:pk>/results/", views.tournament_results, name="tournament_results"),
    path("results/", views.results_overview, name="results_overview"),
]
