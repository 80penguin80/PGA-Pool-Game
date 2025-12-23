from datetime import datetime
import requests
from bs4 import BeautifulSoup
from collections import Counter

from decimal import Decimal
from django.db.models import Sum
from django.shortcuts import render
from django.db.models import Q
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.db.models import Sum,Count
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.contrib.auth import get_user_model

from .services import sync_tournament_earnings
from .models import Season, Tournament, Pick, Player, Result
from .forms import PickForm

def _day_suffix(day: int) -> str:
    if 11 <= day <= 13:
        return "th"
    last = day % 10
    if last == 1:
        return "st"
    if last == 2:
        return "nd"
    if last == 3:
        return "rd"
    return "th"

def _pretty_datetime(iso_str: str) -> str:
    """
    Convert 2026-01-08T08:00Z -> January 8th, 2026 at 8am
    """
    if not iso_str:
        return ""

    iso_str = iso_str.replace("Z", "")
    try:
        dt = datetime.fromisoformat(iso_str)
    except ValueError:
        # If format is unexpected, return raw string
        return iso_str

    month = dt.strftime("%B")
    day = dt.day
    year = dt.year
    suffix = _day_suffix(day)

@login_required
def dashboard(request):
    # Be a bit safer in case no active season
    try:
        season = Season.objects.get(is_active=True)
    except Season.DoesNotExist:
        season = None
    User = get_user_model()

    upcoming_tournaments = []
    total_earnings = 0
    leaderboard = []
    kpis = {}
    participants_count = 0
    pot_total = participants_count * 100

    if season:
        # NEXT 3 UPCOMING TOURNAMENTS
        upcoming_tournaments = (
            Tournament.objects
            .filter(season=season, status="upcoming")
            .order_by("start_date")[:3]
        )

        # all picks in this season
        season_picks = Pick.objects.filter(tournament__season=season)
        participants_count = User.objects.count()

        # current user's season total (used by hero + KPI)
        user_picks = season_picks.filter(user=request.user)
        total_earnings = (
            user_picks.aggregate(total=Sum("earnings"))["total"]
            or 0
        )

        # leaderboard for all users this season
        leaderboard = (
            season_picks
            .values("user__username")
            .annotate(total_earnings=Sum("earnings"))
            .order_by("-total_earnings", "user__username")
        )

        # ----- KPI #3: Earnings Away From 1st -----
        earnings_away_from_first = None
        if leaderboard:
            leader_total = leaderboard[0]["total_earnings"] or 0
            diff = leader_total - total_earnings
            earnings_away_from_first = diff if diff > 0 else 0

        # Use first upcoming tournament as "this week"
        current_tournament = upcoming_tournaments[0] if upcoming_tournaments else None

        current_pick_name = None       # KPI #1 (main)
        current_backup_name = None     # KPI #1 (backup)
        missing_picks_this_week = None # KPI #4

        if current_tournament:
            # ----- KPI #1: Current Pick (+ Backup) -----
            user_pick = (
                Pick.objects
                .filter(user=request.user, tournament=current_tournament)
                .first()
            )

            # Try a few likely field names so it doesn't crash regardless of exact model
            if user_pick:
                current_pick_name = (
                    getattr(user_pick, "player", None)
                    or getattr(user_pick, "player_name", None)
                    or getattr(user_pick, "pick", None)
                )

                current_backup_name = (
                    getattr(user_pick, "backup_player", None)
                    or getattr(user_pick, "backup_player_name", None)
                    or getattr(user_pick, "backup", None)
                )

            # ----- KPI #4: Missing Picks (This Week) -----
            participants_count = season_picks.values("user").distinct().count()
            picks_this_event = (
                Pick.objects
                .filter(tournament=current_tournament)
                .values("user")
                .distinct()
                .count()
            )
            missing_picks_this_week = max(participants_count - picks_this_event, 0)

        # build KPI dict for template
        kpis = {
            "current_pick": current_pick_name,
            "current_backup_pick": current_backup_name,
            "user_total_earnings": total_earnings,
            "earnings_away_from_first": earnings_away_from_first,
            "missing_picks_this_week": missing_picks_this_week,
        }

    context = {
        "season": season,
        "upcoming_tournaments": upcoming_tournaments,
        "total_earnings": total_earnings,
        "leaderboard": leaderboard,
        "kpis": kpis,
        "participants_count": participants_count,
        "pot_total": pot_total,
    }
    return render(request, "core/dashboard.html", context)

def signup(request):
    if request.method == "POST":
        access_code = request.POST.get("access_code", "").strip().lower()

        # Your secret code:
        REQUIRED_CODE = "orange"

        if access_code != REQUIRED_CODE.lower():
            form = UserCreationForm(request.POST)
            form.add_error(None, "Invalid league access code.")
            return render(request, "core/signup.html", {"form": form})

        form = UserCreationForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("login")

    else:
        form = UserCreationForm()

    return render(request, "core/signup.html", {"form": form})

@login_required
def my_picks(request):
    season = (
        Season.objects
        .filter(is_active=True)
        .order_by("-year")
        .first()
    )

    picks = []
    league_picks = []
    kpis = {
        "total_events_played": 0,
        "total_cuts_made": 0,
        "total_events_missed": 0,
        "cut_rate": None,
        "cut_streak": 0,
    }

    if season:
        # All your picks in this season (for display)
        picks = (
            Pick.objects
            .filter(user=request.user, tournament__season=season)
            .select_related("tournament")
            .order_by("tournament__start_date")
        )

        # ALL league picks for ALL tournaments in the season
        league_picks = (
            Pick.objects
            .filter(tournament__season=season)
            .select_related("tournament", "user")
            .order_by("tournament__start_date", "user__username")
        )

        # Tournaments that have results (i.e., scored events)
        completed_events_qs = (
            Tournament.objects
            .filter(season=season, results__isnull=False)
            .distinct()
        )
        total_completed_events = completed_events_qs.count()

        # Your picks ONLY for tournaments that have results
        completed_picks = (
            picks.filter(tournament__in=completed_events_qs)
            .order_by("tournament__start_date")
        )

        # Total Events Played (completed events where you actually picked)
        total_events_played = (
            completed_picks
            .values("tournament")
            .distinct()
            .count()
        )

        # Total Cuts Made (completed events where earnings > 0)
        total_cuts_made = (
            completed_picks
            .filter(earnings__gt=0)
            .values("tournament")
            .distinct()
            .count()
        )

        # Total Events Missed (completed events where you had NO pick)
        total_events_missed = max(
            total_completed_events - total_events_played,
            0
        )

        # Cut Rate % (based on events played)
        if total_events_played > 0:
            cut_rate = (total_cuts_made / total_events_played) * 100
        else:
            cut_rate = None

        # Streak of Made Cuts (from most recent completed pick backwards)
        cut_streak = 0
        completed_list = list(completed_picks)  # ordered ascending
        for pick in reversed(completed_list):
            if pick.earnings and pick.earnings > 0:
                cut_streak += 1
            else:
                break

        kpis = {
            "total_events_played": total_events_played,
            "total_cuts_made": total_cuts_made,
            "total_events_missed": total_events_missed,
            "cut_rate": cut_rate,
            "cut_streak": cut_streak,
        }

    return render(request, "core/my_picks.html", {
        "season": season,
        "picks": picks,
        "league_picks": league_picks,
        "kpis": kpis,
    })


@login_required
def make_picks(request, pk):
    tournament = get_object_or_404(Tournament, pk=pk)

    if timezone.now() >= tournament.pick_lock_datetime:
        return redirect("core:tournament_detail", pk=tournament.pk)

    field_data = fetch_espn_leaderboard(tournament)
    player_names = [row["player"] for row in field_data if row.get("player")]

    # Convert list into Django "choices"
    choices = [(name, name) for name in player_names]

    existing_pick = Pick.objects.filter(user=request.user, tournament=tournament).first()

    if request.method == "POST":
        form = PickForm(
            request.POST,
            user=request.user,
            tournament=tournament,
            instance=existing_pick,
            )

        form.fields["primary_player"].choices = choices
        form.fields["backup_player"].choices = choices

        if form.is_valid():
            pick = form.save(commit=False)
            pick.user = request.user
            pick.tournament = tournament
            pick.active_player = pick.primary_player
            pick.status = "pending"
            pick.reason = "normal"
            pick.save()
            return redirect("core:tournament_detail", pk=tournament.pk)
    else:
        form = PickForm(
            user=request.user,
            tournament=tournament,
            instance=existing_pick,
        )

        form.fields["primary_player"].choices = choices
        form.fields["backup_player"].choices = choices


    return render(
        request,
        "core/make_picks.html",
        {"tournament": tournament, "form": form},
    )

def fetch_espn_leaderboard(tournament):
    """
    Scrape ESPN leaderboard for a given Tournament using tournament.pga_tournament_id.
    Returns a list of dicts: {"player": ..., "tee_time": ...}
    """
    if not tournament.pga_tournament_id:
        return []

    url = f"https://www.espn.com/golf/leaderboard?tournamentId={tournament.pga_tournament_id}"

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=5,
        )
        resp.raise_for_status()
    except requests.RequestException:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.select_one("table.Full__Table")
    if not table:
        return []

    def safe_text(tds, idx):
        return tds[idx].get_text(strip=True) if len(tds) > idx else ""

    rows = []
    for tr in table.select("tbody tr"):
        tds = tr.find_all("td")
        # skip garbage/short rows
        if len(tds) < 2:
            continue

        # Player name is in col 1
        name_tag = tds[1].select_one("a.leaderboard_player_name")
        player = name_tag.get_text(strip=True) if name_tag else safe_text(tds, 2)
        if not player:
            continue

        # col 2 (idx 2) is usually tee time / score / status; safe if missing
        tee_info = safe_text(tds, 1)

        rows.append({
            "player": player,
            "tee_time": tee_info,
        })

    return rows

def fetch_espn_results(tournament, persist=False):
    """
    Scrape ESPN final results for a completed tournament.
    Uses the /_/tournamentId/{id} URL.
    Returns list of dicts with Player, Pos, R1-R4, Total, Earnings.
    If persist=True, also writes into Result and syncs Pick.earnings.
    """
    if not tournament.pga_tournament_id:
        return []

    url = f"https://www.espn.com/golf/leaderboard/_/tournamentId/{tournament.pga_tournament_id}"

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=5,
        )
        resp.raise_for_status()
    except requests.RequestException:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.select_one("table.Full__Table")
    if not table:
        return []

    def safe(tds, idx):
        return tds[idx].get_text(strip=True) if len(tds) > idx else ""

    rows = []
    for tr in table.select("tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue

        pos = safe(tds, 1)
        player = safe(tds, 2)

        r1 = safe(tds, 4)
        r2 = safe(tds, 5)
        r3 = safe(tds, 6)
        r4 = safe(tds, 7)
        total = safe(tds, 8)
        earnings = safe(tds, 9)

        rows.append({
            "Player": player,
            "Pos": pos,
            "R1": r1,
            "R2": r2,
            "R3": r3,
            "R4": r4,
            "Total": total,
            "Earnings": earnings,
        })

    if persist:
        _upsert_results_from_rows(tournament, rows)

    return rows


def fetch_current_leaderboard(tournament):
    """
    Scrape ESPN's current leaderboard for an in-progress tournament.
    Returns list of dicts with:
    POS, PLAYER, SCORE, TODAY, THRU, R1, R2, R3, R4, TOT
    """
    if not tournament.pga_tournament_id:
        return []

    url = f"https://www.espn.com/golf/leaderboard/_/tournamentId/{tournament.pga_tournament_id}"

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=5,
        )
        resp.raise_for_status()
    except requests.RequestException:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.select_one("table.Full__Table")
    if not table:
        return []

    def safe(tds, idx):
        return tds[idx].get_text(strip=True) if len(tds) > idx else ""

    rows = []
    for tr in table.select("tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue

        pos = safe(tds, 1)
        player = safe(tds, 3)
        score = safe(tds, 4)
        today = safe(tds, 5)
        thru = safe(tds, 6)

        r1 = safe(tds, 7)
        r2 = safe(tds, 8)
        r3 = safe(tds, 9    )
        r4 = safe(tds, 10)
        total = safe(tds, 11)

        rows.append({
            "POS": pos,
            "PLAYER": player,
            "SCORE": score,
            "TODAY": today,
            "THRU": thru,
            "R1": r1,
            "R2": r2,
            "R3": r3,
            "R4": r4,
            "TOT": total,
        })

    return rows

@login_required
def tournament_results(request, pk):
    tournament = get_object_or_404(Tournament, pk=pk)
    user_pick = Pick.objects.filter(user=request.user, tournament=tournament).first()

    mode, results = get_espn_leaderboard_for_tournament(tournament)

    return render(
        request,
        "core/tournament_results.html",
        {
            "tournament": tournament,
            "results": results,
            "user_pick": user_pick,
            "mode": mode,
        },
    )

def get_espn_leaderboard_for_tournament(tournament):
    if (tournament.status or "").lower().strip() == "cancelled":
        return "field", []

    status = tournament.status_auto
    print("DEBUG status_auto:", status, "id:", tournament.id)

    if status == "in_progress":
        mode = "live"
        results = fetch_current_leaderboard(tournament)
    elif status == "completed":
        mode = "final"
        # IMPORTANT: persist=True so we write into Result and sync Picks
        results = fetch_espn_results(tournament, persist=True)
    else:
        mode = "field"
        results = fetch_espn_leaderboard(tournament)

    return mode, results


@login_required
def tournament_list(request):
    """
    Simple list of tournaments for the active season.
    """
    season = Season.objects.filter(is_active=True).order_by("-year").first()
    if season:
        tournaments = Tournament.objects.filter(season=season).order_by("start_date")
    else:
        tournaments = Tournament.objects.none()

    return render(
        request,
        "core/tournament_list.html",
        {
            "season": season,
            "tournaments": tournaments,
        },
    )

@login_required
def tournament_detail(request, pk):
    """
    Simple detail view for a single tournament + pool picks.
    """
    tournament = get_object_or_404(Tournament, pk=pk)

    user_pick = Pick.objects.filter(
        user=request.user,
        tournament=tournament,
    ).first()

    league_picks = (
        Pick.objects
        .filter(tournament=tournament)
        .select_related("user")
        .order_by("user__username")
    )

    return render(
        request,
        "core/tournament_detail.html",
        {
            "tournament": tournament,
            "user_pick": user_pick,
            "league_picks": league_picks,
        },
    )
def _parse_earnings(val: str) -> Decimal:
    """
    Convert ESPN earnings text like '$621,000' or '—' to Decimal.
    """
    if not val:
        return Decimal("0")
    val = val.replace("$", "").replace(",", "").strip()
    if not val or val in {"—", "-", "--"}:
        return Decimal("0")
    try:
        return Decimal(val)
    except Exception:
        return Decimal("0")


def _upsert_results_from_rows(tournament, rows):
    """
    Take rows from fetch_espn_results and upsert into Result,
    then sync Pick.earnings.

    IMPORTANT:
    - Do NOT overwrite a non-zero manual earning with 0 from ESPN.
    """
    from .models import Player, Result  # local import to avoid cycles

    for row in rows:
        name = (row.get("Player") or "").strip()
        if not name:
            continue

        earnings = _parse_earnings(row.get("Earnings", ""))
        pos = (row.get("Pos") or "").strip()
        total = (row.get("Total") or "").strip()

        # crude made_cut flag: MC/WD/DQ treated as missed
        made_cut = total not in {"MC", "WD", "DQ", ""}

        first, *rest = name.split()
        last = " ".join(rest) or None

        player, _ = Player.objects.get_or_create(
            full_name=name,
            defaults={
                "first_name": first,
                "last_name": last,
            },
        )

        result, created = Result.objects.get_or_create(
            tournament=tournament,
            player=player,
            defaults={
                "position": pos or total or "",
                "earnings": earnings,
                "made_cut": made_cut,
            },
        )

        if not created:
            # Always update position / made_cut
            result.position = pos or total or result.position
            result.made_cut = made_cut

            # If ESPN says 0 but we already have a non-zero value, keep the manual value.
            if not (earnings == Decimal("0") and result.earnings and result.earnings > 0):
                result.earnings = earnings

            result.save()

    # After results are saved, push earnings into Pick.earnings
    sync_tournament_earnings(tournament)


@login_required
def standings(request):
    season = Season.objects.filter(is_active=True).order_by("-year").first()
    rows = []
    kpis = {
        "avg_earnings_per_user": 0,
        "total_earnings": 0,
        "most_picked_golfer": None,
        "most_picked_golfer_count": 0,
        "cut_rate": None,
    }

    if season:
        picks_qs = (
            Pick.objects
            .filter(tournament__season=season)
            .select_related("user", "tournament")
        )

        # ---------- KPI #3: Most Picked Golfer (across all events) ----------
        primary_names = [
            p.primary_player
            for p in picks_qs
            if getattr(p, "primary_player", None)
        ]

        most_picked_golfer = None
        most_picked_golfer_count = 0
        if primary_names:
            counter = Counter(primary_names)
            most_picked_golfer, most_picked_golfer_count = counter.most_common(1)[0]

        # ---------- Per-user standings + league-level stats ----------
        by_tournament = {}
        for p in picks_qs:
            by_tournament.setdefault(p.tournament_id, []).append(p)

        stats = {}  # user_id -> dict

        league_total_earnings = 0.0           # KPI #2
        league_total_picks_scored = 0         # for cut rate
        league_cashes = 0                     # picks with earnings > 0

        for tournament_id, picks in by_tournament.items():
            # skip tournaments that have not been scored (all zero / None earnings)
            if not any((p.earnings or 0) > 0 for p in picks):
                continue

            # Only scored events reach here
            ranked = sorted(
                picks,
                key=lambda p: (-(p.earnings or 0), p.user.username),
            )

            for idx, p in enumerate(ranked):
                rank = idx + 1
                earnings = float(p.earnings or 0)

                # league totals for KPIs
                league_total_earnings += earnings
                league_total_picks_scored += 1
                if earnings > 0:
                    league_cashes += 1

                user_id = p.user_id
                s = stats.setdefault(user_id, {
                    "user": p.user,
                    "points": 0.0,
                    "wins": 0,
                    "top5": 0,
                    "top10": 0,
                    "cashes": 0,
                    "events": 0,
                })

                # Events = scored events where user had a pick
                s["events"] += 1
                s["points"] += earnings

                if earnings > 0:
                    s["cashes"] += 1
                if rank == 1:
                    s["wins"] += 1
                if rank <= 5:
                    s["top5"] += 1
                if rank <= 10:
                    s["top10"] += 1

        rows = list(stats.values())
        rows.sort(
            key=lambda r: (
                -r["points"],
                -r["wins"],
                -r["top5"],
                -r["top10"],
                r["user"].username,
            )
        )

        # ---------- KPIs ----------

        # KPI #1: Avg Earnings Per User (only users with at least one scored event)
        user_count = len(stats)
        if user_count > 0:
            avg_earnings_per_user = league_total_earnings / user_count
        else:
            avg_earnings_per_user = 0

        # KPI #4: League Cut Rate % (scored picks with earnings > 0)
        if league_total_picks_scored > 0:
            cut_rate = (league_cashes / league_total_picks_scored) * 100
        else:
            cut_rate = None

        kpis = {
            "avg_earnings_per_user": avg_earnings_per_user,
            "total_earnings": league_total_earnings,
            "most_picked_golfer": most_picked_golfer,
            "most_picked_golfer_count": most_picked_golfer_count,
            "cut_rate": cut_rate,
        }

    context = {
        "season": season,
        "rows": rows,
        "kpis": kpis,
    }
    return render(request, "core/standings.html", context)


@login_required
def results_overview(request):
    completed = Tournament.objects.filter(status="completed").order_by("-start_date")
    return render(request, "core/results_overview.html", {"tournaments": completed})

def rules(request):
    return render(request, "core/rules.html")

