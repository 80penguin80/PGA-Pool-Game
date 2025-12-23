from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import datetime, time


User = get_user_model()


class Season(models.Model):
    name = models.CharField(max_length=100)  # e.g. "2026 Season"
    year = models.IntegerField()
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-year", "name"]

    def __str__(self):
        return f"{self.name} ({self.year})"


class Tournament(models.Model):
    STATUS_CHOICES = [
        ("upcoming", "Upcoming"),
        ("in_progress", "In Progress"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="tournaments")
    name = models.CharField(max_length=200)
    pga_tournament_id = models.CharField(
        max_length=50, blank=True, null=True,
        help_text="Optional external ID if you scrape PGA data."
    )
    start_date = models.DateField()
    end_date = models.DateField()
    pick_lock_datetime = models.DateTimeField(
        help_text="When picks lock (usually first tee time)."
    )
    purse = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    multiplier = models.DecimalField(
        max_digits=4, decimal_places=2, default=1.00,
        help_text="1.00 normal, 2.00 for majors, etc."
    )
    is_major = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="upcoming")
    @property
    def status_auto(self):
        """
        Compute status from dates:
        - upcoming: today < start_date
        - in_progress: start_date <= today <= end_date
        - completed: today > end_date
        """
        now = timezone.now()

        # If dates missing, treat as upcoming
        if not self.start_date or not self.end_date:
            return "upcoming"

        # If no pick_lock, fall back to simple date logic
        if not self.pick_lock_datetime:
            today = timezone.localdate()
            if today < self.start_date:
                return "upcoming"
            elif today > self.end_date:
                return "completed"
            else:
                return "in_progress"

        # Build "end of day" for end_date, make it aware if needed
        end_of_day = datetime.combine(self.end_date, time(23, 59, 59))
        if timezone.is_naive(end_of_day):
            end_of_day = timezone.make_aware(end_of_day, timezone.get_current_timezone())

        # Main logic
        if now < self.pick_lock_datetime:
            return "upcoming"
        elif now <= end_of_day:
            return "in_progress"
        else:
            return "completed"


    class Meta:
        ordering = ["start_date", "name"]

    def __str__(self):
        return f"{self.name} ({self.season.year})"


class Player(models.Model):
    pga_player_id = models.CharField(
        max_length=50, blank=True, null=True,
        help_text="Optional external player ID."
    )
    first_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100, blank=True, null=True)
    full_name = models.CharField(max_length=200, unique=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name


class TournamentField(models.Model):
    STATUS_CHOICES = [
        ("in_field", "In Field"),
        ("wd", "Withdrawn"),
        ("dq", "Disqualified"),
    ]

    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="field")
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="tournament_entries")
    tee_time = models.DateTimeField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="in_field")

    class Meta:
        unique_together = ("tournament", "player")
        ordering = ["tournament", "player__full_name"]

    def __str__(self):
        return f"{self.player} @ {self.tournament}"


class Result(models.Model):
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="results")
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="results")
    position = models.CharField(
        max_length=10,
        help_text='e.g. "1", "T3", "MC", "WD", "DQ"',
    )
    earnings = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    made_cut = models.BooleanField(default=False)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        unique_together = ("tournament", "player")
        ordering = ["tournament", "position"]

    def __str__(self):
        return f"{self.player} – {self.tournament} – {self.position} (${self.earnings})"


class Pick(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("locked", "Locked"),
        ("void", "Void"),
    ]

    REASON_CHOICES = [
        ("normal", "Normal"),
        ("primary_wd_pre_start", "Primary WD pre-start, backup used"),
        ("manual_override", "Manual override"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="picks")
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="picks")

    # ────────────────────────────────────────────────
    # CHANGED: Player names are now plain text fields
    # ────────────────────────────────────────────────

    primary_player = models.CharField(
        max_length=100,
        help_text="Name of the primary player exactly as fetched from ESPN."
    )

    backup_player = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Backup player from ESPN list (optional)."
    )

    active_player = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="The player that actually counts for scoring."
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    reason = models.CharField(max_length=30, choices=REASON_CHOICES, default="normal")

    earnings = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Final earnings for this pick, stored for speed."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "tournament")  # one pick per user per tournament
        ordering = ["tournament__start_date", "user__username"]

    def __str__(self):
        return f"{self.user} – {self.tournament} – {self.active_player or self.primary_player}"


class UserSeasonStats(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="season_stats")
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="user_stats")

    total_earnings = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    majors_earnings = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    weeks_played = models.IntegerField(default=0)
    weekly_wins = models.IntegerField(default=0)
    top5_finishes = models.IntegerField(default=0)

    class Meta:
        unique_together = ("user", "season")
        ordering = ["-total_earnings"]

    def __str__(self):
        return f"{self.user} – {self.season} – ${self.total_earnings}"
