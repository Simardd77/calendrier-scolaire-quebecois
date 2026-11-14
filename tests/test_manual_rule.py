"""Tests de la conversion d'un evenement de la vue des calendriers en regle."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest

from custom_components.calendrier_scolaire_quebecois.const import CONF_MANUAL_EVENTS
from custom_components.calendrier_scolaire_quebecois.manual_rule import (
    add_manual_rule,
    manual_event_from_calendar,
)

TZ = ZoneInfo("America/Toronto")


def _convert(**overrides):
    args = {
        "summary": "Éducation physique",
        "dtstart": datetime(2026, 11, 16, 10, 0, tzinfo=TZ),
        "dtend": datetime(2026, 11, 16, 11, 0, tzinfo=TZ),
        "rrule": None,
        "description": None,
        "location": None,
        "tz": TZ,
    }
    args.update(overrides)
    return manual_event_from_calendar(**args)


# --- Evenements ponctuels ----------------------------------------------------


def test_ponctuel_horodate():
    rule = _convert()
    assert rule.start_date == rule.end_date == date(2026, 11, 16)
    assert rule.weekdays == ()
    assert (rule.start_time, rule.end_time) == (time(10, 0), time(11, 0))
    assert rule.skip_closures is True


def test_ponctuel_journee_entiere():
    rule = _convert(dtstart=date(2026, 11, 16), dtend=date(2026, 11, 17))
    assert rule.all_day
    assert rule.start_date == rule.end_date == date(2026, 11, 16)


def test_heure_lue_dans_le_fuseau_local():
    """15 h UTC en novembre est 10 h a Montreal (UTC-5)."""
    rule = _convert(
        dtstart=datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc),
        dtend=datetime(2026, 11, 16, 16, 0, tzinfo=timezone.utc),
    )
    assert rule.start_time == time(10, 0)
    assert rule.end_time == time(11, 0)


# --- Repetitions prises en charge -------------------------------------------


def test_hebdomadaire_mardi_jeudi_jusqu_a_une_date():
    rule = _convert(
        dtstart=datetime(2026, 11, 17, 10, 0, tzinfo=TZ),
        dtend=datetime(2026, 11, 17, 11, 0, tzinfo=TZ),
        rrule="FREQ=WEEKLY;BYDAY=TU,TH;UNTIL=20261130",
    )
    assert rule.weekdays == (1, 3)
    assert rule.end_date == date(2026, 11, 30)
    assert rule.start_time == time(10, 0)


def test_exemple_du_16_au_30_novembre_le_lundi():
    rule = _convert(
        dtstart=datetime(2026, 11, 16, 14, 0, tzinfo=TZ),
        dtend=datetime(2026, 11, 16, 15, 0, tzinfo=TZ),
        rrule="FREQ=WEEKLY;BYDAY=MO;UNTIL=20261130",
    )
    assert (rule.start_date, rule.end_date) == (date(2026, 11, 16), date(2026, 11, 30))
    assert rule.weekdays == (0,)
    assert (rule.start_time, rule.end_time) == (time(14, 0), time(15, 0))


def test_hebdomadaire_sans_byday_prend_le_jour_du_debut():
    rule = _convert(rrule="FREQ=WEEKLY;UNTIL=20261207")
    assert rule.weekdays == (0,)  # le 16 novembre 2026 est un lundi


def test_until_en_utc_ramene_en_date_locale():
    """Fin de journee locale (23 h 59 a Montreal) = lendemain en UTC."""
    rule = _convert(rrule="FREQ=WEEKLY;BYDAY=MO;UNTIL=20261201T045959Z")
    assert rule.end_date == date(2026, 11, 30)


def test_until_local_sans_z():
    rule = _convert(rrule="FREQ=WEEKLY;BYDAY=MO;UNTIL=20261130T235959")
    assert rule.end_date == date(2026, 11, 30)


def test_count_calcule_la_date_de_fin():
    # Lundis a partir du 16 novembre: 16, 23, 30 -> la 3e est le 30.
    rule = _convert(rrule="FREQ=WEEKLY;BYDAY=MO;COUNT=3")
    assert rule.end_date == date(2026, 11, 30)


def test_count_avec_plusieurs_jours():
    # Mardi et jeudi depuis le mardi 17: 17, 19, 24, 26 -> la 4e est le 26.
    rule = _convert(
        dtstart=datetime(2026, 11, 17, 10, 0, tzinfo=TZ),
        dtend=datetime(2026, 11, 17, 11, 0, tzinfo=TZ),
        rrule="FREQ=WEEKLY;BYDAY=TU,TH;COUNT=4",
    )
    assert rule.end_date == date(2026, 11, 26)


def test_quotidien_couvre_les_sept_jours():
    rule = _convert(rrule="FREQ=DAILY;UNTIL=20261120")
    assert rule.weekdays == (0, 1, 2, 3, 4, 5, 6)


def test_interval_un_explicite_accepte():
    assert _convert(rrule="FREQ=WEEKLY;INTERVAL=1;BYDAY=MO;COUNT=2").weekdays == (0,)


def test_journee_entiere_recurrente():
    rule = _convert(
        dtstart=date(2026, 11, 16),
        dtend=date(2026, 11, 17),
        rrule="FREQ=WEEKLY;BYDAY=MO;UNTIL=20261130",
    )
    assert rule.all_day
    assert rule.weekdays == (0,)


def test_identifiant_identique_a_celui_du_formulaire_d_options():
    from custom_components.calendrier_scolaire_quebecois.models import (
        build_manual_event_id,
    )

    rule = _convert(rrule="FREQ=WEEKLY;BYDAY=MO;COUNT=3")
    assert rule.event_id == build_manual_event_id(
        "Éducation physique", date(2026, 11, 16), (0,), time(10, 0)
    )


# --- Refus -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rrule", "fragment"),
    [
        ("FREQ=WEEKLY;INTERVAL=2;BYDAY=MO;COUNT=3", "une semaine sur deux"),
        ("FREQ=WEEKLY;BYDAY=3MO;COUNT=3", "3e lundi"),
        ("FREQ=MONTHLY;COUNT=3", "quotidiennes et hebdomadaires"),
        ("FREQ=YEARLY;COUNT=3", "quotidiennes et hebdomadaires"),
        ("FREQ=WEEKLY;BYMONTH=11;COUNT=3", "BYMONTH"),
        ("FREQ=WEEKLY;BYDAY=MO", "Indiquez la fin"),
        ("FREQ=WEEKLY;BYDAY=MO;UNTIL=20261130;COUNT=3", "combines"),
        ("FREQ=WEEKLY;BYDAY=MO;COUNT=0", "entre 1 et"),
        ("FREQ=WEEKLY;BYDAY=MO;COUNT=5000", "entre 1 et"),
        ("FREQ=WEEKLY;BYDAY=MO;COUNT=abc", "invalide"),
        ("FREQ=WEEKLY;BYDAY=MO;UNTIL=demain", "illisible"),
    ],
)
def test_repetitions_refusees(rrule, fragment):
    with pytest.raises(ValueError, match=fragment):
        _convert(rrule=rrule)


def test_description_refusee():
    with pytest.raises(ValueError, match="description"):
        _convert(description="Apporter des espadrilles")


def test_lieu_refuse():
    with pytest.raises(ValueError, match="lieu"):
        _convert(location="Gymnase")


def test_description_vide_acceptee():
    assert _convert(description="  ", location="").summary == "Éducation physique"


def test_horodate_sur_deux_jours_refuse():
    with pytest.raises(ValueError, match="meme jour"):
        _convert(
            dtstart=datetime(2026, 11, 16, 14, 0, tzinfo=TZ),
            dtend=datetime(2026, 11, 17, 13, 0, tzinfo=TZ),
        )


def test_journee_entiere_sur_plusieurs_jours_refusee():
    with pytest.raises(ValueError, match="plusieurs jours"):
        _convert(dtstart=date(2026, 11, 16), dtend=date(2026, 11, 30))


def test_fin_avant_le_debut_refusee():
    with pytest.raises(ValueError):
        _convert(rrule="FREQ=WEEKLY;BYDAY=MO;UNTIL=20261101")


def test_titre_vide_refuse():
    with pytest.raises(ValueError):
        _convert(summary="   ")


# --- add_manual_rule ---------------------------------------------------------


def test_ajout_aux_options_conserve_le_reste():
    rule = _convert()
    options = add_manual_rule({"refresh_interval": 600}, rule, "Test")
    assert options["refresh_interval"] == 600
    assert options[CONF_MANUAL_EVENTS] == [rule.as_dict()]


def test_ajout_ne_modifie_pas_les_options_d_origine():
    original = {CONF_MANUAL_EVENTS: []}
    add_manual_rule(original, _convert(), "Test")
    assert original == {CONF_MANUAL_EVENTS: []}


def test_ajout_refuse_un_doublon():
    rule = _convert()
    options = add_manual_rule({}, rule, "Test")
    with pytest.raises(ValueError, match="identique"):
        add_manual_rule(options, rule, "Test")
