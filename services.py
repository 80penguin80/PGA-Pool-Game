# core/services.py
from decimal import Decimal

from .models import Tournament, Pick, Result


def _norm(name: str) -> str:
    return " ".join(name.strip().lower().split())


from decimal import Decimal

def sync_tournament_earnings(tournament: Tournament):

    if not tournament.pga_tournament_id:
        print(f"Skipping sync for '{tournament.name}' (no PGA ID)")
        return

    multiplier = Decimal(tournament.multiplier or 1)

    results = (
        Result.objects
        .filter(tournament=tournament)
        .select_related("player")
    )

    name_to_result = {}
    for r in results:
        full_name = (r.player.full_name or "").strip()
        if not full_name:
            continue
        name_to_result[_norm(full_name)] = r

    picks = Pick.objects.filter(tournament=tournament)

    for p in picks:
        raw_name = p.active_player or p.primary_player
        if not raw_name:
            p.earnings = Decimal("0")
            p.save(update_fields=["earnings"])
            continue

        key = _norm(raw_name)
        r = name_to_result.get(key)

        if r is None:
            p.earnings = Decimal("0")
        else:
            p.earnings = (r.earnings or Decimal("0")) * multiplier

        p.save(update_fields=["earnings"])

