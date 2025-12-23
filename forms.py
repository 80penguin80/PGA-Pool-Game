from django import forms
from django.utils import timezone
from .models import Pick


class PickForm(forms.ModelForm):

    # These will be turned into dropdowns by assigning .choices in the view
    primary_player = forms.ChoiceField(choices=[])
    backup_player = forms.ChoiceField(choices=[], required=False)

    class Meta:
        model = Pick
        fields = ["primary_player", "backup_player"]

    def __init__(self, *args, **kwargs):
        # remove unused Player FK references
        self.user = kwargs.pop("user")
        self.tournament = kwargs.pop("tournament")
        super().__init__(*args, **kwargs)

        # Labels
        self.fields["primary_player"].label = "Primary golfer"
        self.fields["backup_player"].label = "Backup golfer (optional)"

        # IMPORTANT:
        # choices are assigned in the view (make_picks), NOT here anymore.
        # Here they stay empty until the view fills them in.

    def clean(self):
        cleaned_data = super().clean()
        primary = cleaned_data.get("primary_player")   # now strings, not Player objects
        backup  = cleaned_data.get("backup_player")

        # 1) Picks locked?
        if timezone.now() >= self.tournament.pick_lock_datetime:
            raise forms.ValidationError("Picks are locked for this tournament.")

        # 2) Primary != backup
        if primary and backup and primary == backup:
            raise forms.ValidationError("Primary and backup golfer must be different.")

        # 3) No-repeat rule (string comparison now!)
        if primary and self._player_used_this_season(primary):
            raise forms.ValidationError(f"You've already used {primary} this season.")

        if backup and self._player_used_this_season(backup):
            raise forms.ValidationError(f"You've already used {backup} this season.")

        return cleaned_data

    def _player_used_this_season(self, name: str) -> bool:
        """Check if user already used this golfer name during the season."""

        season = self.tournament.season

        qs = Pick.objects.filter(
            user=self.user,
            tournament__season=season,
            active_player=name,   # name is a plain string now
        )

        # Exclude the current pick when editing
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)

        return qs.exists()
