"""Suppression d'evenements manuels depuis la vue des calendriers: logique pure.

Une regle hebdomadaire sert de reference: le lundi 16, 23 et 30 novembre 2026,
de 14 h a 15 h.
"""

from __future__ import annotations

from datetime import date, time
from zoneinfo import ZoneInfo

import pytest

from custom_components.calendrier_scolaire_quebecois.const import CONF_MANUAL_EVENTS
from custom_components.calendrier_scolaire_quebecois.manual_rule import (
    RANGE_THIS_AND_FUTURE,
    delete_manual_occurrence,
)
from custom_components.calendrier_scolaire_quebecois.models import (
    ManualEvent,
    expand_manual_event,
    manual_rrule,
    rule_days,
)

TZ = ZoneInfo("America/Toronto")
LUNDI_16, LUNDI_23, LUNDI_30 = (
    date(2026, 11, 16),
    date(2026, 11, 23),
    date(2026, 11, 30),
)


def _rule(**overrides) -> ManualEvent:
    args = {
        "event_id": "serie1",
        "summary": "Éducation physique",
        "start_date": LUNDI_16,
        "end_date": LUNDI_30,
        "weekdays": (0,),
        "start_time": time(14, 0),
        "end_time": time(15, 0),
    }
    args.update(overrides)
    return ManualEvent(**args)


def _options(*rules: ManualEvent, **extra) -> dict:
    return {CONF_MANUAL_EVENTS: [rule.as_dict() for rule in rules], **extra}


def _stored(options: dict) -> list[ManualEvent]:
    return [ManualEvent.from_dict(item) for item in options[CONF_MANUAL_EVENTS]]


# --- Modele: dates exclues ----------------------------------------------------


def test_les_journees_exclues_sont_omises():
    rule = _rule(excluded_dates=(LUNDI_23,))
    assert rule_days(rule) == [LUNDI_16, LUNDI_30]


def test_aller_retour_des_dates_exclues_triees():
    rule = _rule(excluded_dates=(LUNDI_30, LUNDI_23))
    data = rule.as_dict()
    assert data["excluded_dates"] == ["2026-11-23", "2026-11-30"]
    assert ManualEvent.from_dict(data) == _rule(excluded_dates=(LUNDI_23, LUNDI_30))


def test_pas_de_cle_quand_rien_n_est_exclu():
    assert "excluded_dates" not in _rule().as_dict()


def test_regle_sans_dates_exclues_se_relit_comme_avant():
    """Les regles enregistrees avant cette fonction n'ont pas la cle."""
    data = _rule().as_dict()
    assert ManualEvent.from_dict(data).excluded_dates == ()


@pytest.mark.parametrize("valeur", ["2026-11-23", 5, [None], ["pas-une-date"]])
def test_dates_exclues_invalides_refusees(valeur):
    data = {**_rule().as_dict(), "excluded_dates": valeur}
    with pytest.raises(ValueError):
        ManualEvent.from_dict(data)


def test_l_identifiant_ne_depend_pas_des_dates_exclues():
    from custom_components.calendrier_scolaire_quebecois.models import (
        build_manual_event_id,
    )

    assert build_manual_event_id("EPS", LUNDI_16, (0,), time(14, 0)) == (
        build_manual_event_id("EPS", LUNDI_16, (0,), time(14, 0))
    )
    # La regle conserve son identifiant quand on lui exclut une journee.
    assert _rule(excluded_dates=(LUNDI_23,)).event_id == _rule().event_id


def test_les_occurrences_excluent_les_journees_retirees():
    rule = _rule(excluded_dates=(LUNDI_23,))
    jours = [event.start.date() for event in expand_manual_event(rule, tz=TZ)]
    assert jours == [LUNDI_16, LUNDI_30]


# --- Modele: serie exposee a la vue des calendriers ---------------------------


def test_rrule_d_une_regle_recurrente():
    assert manual_rrule(_rule()) == "FREQ=WEEKLY;BYDAY=MO;UNTIL=20261130"
    assert (
        manual_rrule(_rule(weekdays=(1, 3))) == "FREQ=WEEKLY;BYDAY=TU,TH;UNTIL=20261130"
    )


def test_pas_de_rrule_pour_un_evenement_ponctuel():
    assert manual_rrule(_rule(weekdays=(), end_date=LUNDI_16)) is None


def test_la_rrule_produite_est_acceptee_par_home_assistant():
    from homeassistant.components.calendar.helper import validate_rrule

    assert validate_rrule(manual_rrule(_rule(weekdays=(0, 2, 4))))


def test_les_occurrences_portent_leur_serie():
    premiere = expand_manual_event(_rule(), tz=TZ)[0]
    assert premiere.extra["manual_event_id"] == "serie1"
    assert premiere.extra["manual_recurrence_id"] == "2026-11-16"
    assert premiere.extra["manual_rrule"] == "FREQ=WEEKLY;BYDAY=MO;UNTIL=20261130"


def test_un_evenement_ponctuel_n_a_ni_recurrence_ni_rrule():
    seul = expand_manual_event(_rule(weekdays=(), end_date=LUNDI_16), tz=TZ)[0]
    assert seul.extra["manual_recurrence_id"] == ""
    assert seul.extra["manual_rrule"] == ""


def test_conversion_en_evenement_home_assistant():
    from custom_components.calendrier_scolaire_quebecois.calendar import (
        _to_calendar_event,
    )

    evenement = _to_calendar_event(expand_manual_event(_rule(), tz=TZ)[1])
    assert evenement.uid == "serie1"
    assert evenement.recurrence_id == "2026-11-23"
    assert evenement.rrule == "FREQ=WEEKLY;BYDAY=MO;UNTIL=20261130"


def test_un_evenement_de_source_garde_son_uid_et_n_a_pas_de_serie():
    from custom_components.calendrier_scolaire_quebecois.calendar import (
        _to_calendar_event,
    )
    from custom_components.calendrier_scolaire_quebecois.models import (
        EventCategory,
        SchoolEvent,
    )

    source = SchoolEvent(
        summary="Congé",
        start=date(2026, 11, 20),
        end=date(2026, 11, 21),
        category=EventCategory.HOLIDAY,
    )
    evenement = _to_calendar_event(source)
    assert evenement.uid == source.uid
    assert evenement.recurrence_id is None
    assert evenement.rrule is None


# --- Suppression --------------------------------------------------------------


def test_evenement_ponctuel_retire_en_entier():
    ponctuel = _rule(weekdays=(), end_date=LUNDI_16)
    autre = _rule(event_id="autre", summary="Chorale")
    options = delete_manual_occurrence(_options(ponctuel, autre), "serie1", None, None)
    assert [rule.event_id for rule in _stored(options)] == ["autre"]


def test_serie_sans_recurrence_id_retiree_en_entier():
    options = delete_manual_occurrence(_options(_rule()), "serie1", None, None)
    assert options[CONF_MANUAL_EVENTS] == []


def test_une_occurrence_seulement():
    options = delete_manual_occurrence(_options(_rule()), "serie1", "2026-11-23", None)
    (rule,) = _stored(options)
    assert rule.event_id == "serie1"
    assert rule.excluded_dates == (LUNDI_23,)
    assert rule_days(rule) == [LUNDI_16, LUNDI_30]


def test_plage_vide_equivaut_a_l_occurrence_seule():
    options = delete_manual_occurrence(_options(_rule()), "serie1", "2026-11-23", "")
    assert _stored(options)[0].excluded_dates == (LUNDI_23,)


def test_retirer_la_derniere_occurrence_retire_la_regle():
    options = _options(_rule())
    for jour in ("2026-11-16", "2026-11-23"):
        options = delete_manual_occurrence(options, "serie1", jour, None)
    assert len(_stored(options)) == 1
    options = delete_manual_occurrence(options, "serie1", "2026-11-30", None)
    assert options[CONF_MANUAL_EVENTS] == []


def test_celui_ci_et_les_suivants_raccourcit_la_serie():
    options = delete_manual_occurrence(
        _options(_rule()), "serie1", "2026-11-23", RANGE_THIS_AND_FUTURE
    )
    (rule,) = _stored(options)
    assert rule.end_date == date(2026, 11, 22)
    assert rule_days(rule) == [LUNDI_16]


def test_celui_ci_et_les_suivants_sur_la_premiere_retire_tout():
    options = delete_manual_occurrence(
        _options(_rule()), "serie1", "2026-11-16", RANGE_THIS_AND_FUTURE
    )
    assert options[CONF_MANUAL_EVENTS] == []


def test_les_exclusions_posterieures_a_la_nouvelle_fin_sont_abandonnees():
    options = delete_manual_occurrence(_options(_rule()), "serie1", "2026-11-30", None)
    options = delete_manual_occurrence(
        options, "serie1", "2026-11-23", RANGE_THIS_AND_FUTURE
    )
    (rule,) = _stored(options)
    assert rule.excluded_dates == ()
    assert rule.end_date == date(2026, 11, 22)


def test_une_exclusion_anterieure_est_conservee():
    options = delete_manual_occurrence(_options(_rule()), "serie1", "2026-11-16", None)
    options = delete_manual_occurrence(
        options, "serie1", "2026-11-30", RANGE_THIS_AND_FUTURE
    )
    (rule,) = _stored(options)
    assert rule.excluded_dates == (LUNDI_16,)
    assert rule_days(rule) == [LUNDI_23]


def test_les_autres_regles_et_options_sont_intactes():
    autre = _rule(event_id="autre", summary="Chorale", weekdays=(2,))
    options = _options(_rule(), autre, refresh_interval=600)
    resultat = delete_manual_occurrence(options, "serie1", "2026-11-23", None)
    assert resultat["refresh_interval"] == 600
    assert resultat[CONF_MANUAL_EVENTS][1] == autre.as_dict()


def test_les_options_d_origine_ne_sont_pas_modifiees():
    options = _options(_rule())
    copie = {CONF_MANUAL_EVENTS: [dict(item) for item in options[CONF_MANUAL_EVENTS]]}
    delete_manual_occurrence(options, "serie1", "2026-11-23", None)
    assert options == copie


@pytest.mark.parametrize(
    ("uid", "recurrence_id", "plage", "fragment"),
    [
        ("inconnu", None, None, "Seuls les evenements manuels"),
        ("serie1", "2026-11-24", None, "n'existe plus"),
        ("serie1", "2026-11-16", "THISEVENT", "non prise en charge"),
        ("serie1", "pas-une-date", None, "invalide"),
    ],
)
def test_suppressions_refusees(uid, recurrence_id, plage, fragment):
    with pytest.raises(ValueError, match=fragment):
        delete_manual_occurrence(_options(_rule()), uid, recurrence_id, plage)


def test_une_occurrence_deja_retiree_n_existe_plus():
    options = delete_manual_occurrence(_options(_rule()), "serie1", "2026-11-23", None)
    with pytest.raises(ValueError, match="n'existe plus"):
        delete_manual_occurrence(options, "serie1", "2026-11-23", None)


# --- Serie reduite a une occurrence -------------------------------------------


def test_une_seule_occurrence_restante_se_presente_comme_ordinaire():
    rule = _rule(excluded_dates=(LUNDI_16, LUNDI_23))  # il ne reste que le 30
    (seule,) = expand_manual_event(rule, tz=TZ)
    assert seule.extra["manual_event_id"] == "serie1"
    assert seule.extra["manual_recurrence_id"] == ""
    assert seule.extra["manual_rrule"] == ""


def test_deux_occurrences_restent_une_serie():
    rule = _rule(excluded_dates=(LUNDI_23,))
    for occurrence in expand_manual_event(rule, tz=TZ):
        assert occurrence.extra["manual_recurrence_id"] != ""
        assert occurrence.extra["manual_rrule"] != ""


def test_conversion_d_une_occurrence_unique_sans_repetition():
    from custom_components.calendrier_scolaire_quebecois.calendar import (
        _to_calendar_event,
    )

    rule = _rule(excluded_dates=(LUNDI_16, LUNDI_23))
    evenement = _to_calendar_event(expand_manual_event(rule, tz=TZ)[0])
    assert evenement.uid == "serie1"
    assert evenement.recurrence_id is None
    assert evenement.rrule is None


def test_supprimer_l_occurrence_unique_sans_recurrence_id_retire_la_regle():
    """La vue n'envoie pas de recurrence_id pour un evenement ordinaire."""
    options = _options(_rule(excluded_dates=(LUNDI_16, LUNDI_23)))
    resultat = delete_manual_occurrence(options, "serie1", None, None)
    assert resultat[CONF_MANUAL_EVENTS] == []
