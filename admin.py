from django.contrib import admin
from .models import Season, Tournament, Player, TournamentField, Result, Pick, UserSeasonStats


@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = ("name", "year", "start_date", "end_date", "is_active")
    list_filter = ("year", "is_active")


@admin.register(Tournament)
class TournamentAdmin(admin.ModelAdmin):
    list_display = ("name", "season", "start_date", "end_date", "status", "is_major", "multiplier")
    list_filter = ("season", "status", "is_major")
    search_fields = ("name",)


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("full_name", "country", "active")
    list_filter = ("active", "country")
    search_fields = ("full_name", "first_name", "last_name")


@admin.register(TournamentField)
class TournamentFieldAdmin(admin.ModelAdmin):
    list_display = ("tournament", "player", "status", "tee_time")
    list_filter = ("tournament", "status")
    search_fields = ("player__full_name",)


@admin.register(Result)
class ResultAdmin(admin.ModelAdmin):
    list_display = ("tournament", "player", "position", "earnings", "made_cut")
    list_filter = ("tournament", "made_cut")
    search_fields = ("player__full_name",)


@admin.register(Pick)
class PickAdmin(admin.ModelAdmin):
    list_display = (
        "user", "tournament", "primary_player", "backup_player",
        "active_player", "status", "reason", "earnings"
    )
    list_filter = ("tournament", "status", "reason")
    search_fields = ("user__username", "primary_player__full_name", "active_player__full_name")


@admin.register(UserSeasonStats)
class UserSeasonStatsAdmin(admin.ModelAdmin):
    list_display = (
        "user", "season", "total_earnings", "majors_earnings",
        "weeks_played", "weekly_wins", "top5_finishes"
    )
    list_filter = ("season",)
    search_fields = ("user__username",)
