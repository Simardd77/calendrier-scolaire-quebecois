"""Tests de l'injection des evenements manuels dans le coordinateur.

build_manual_events est une fonction pure: elle recoit la journee de reference
et le fuseau, donc se teste sans monter d'instance de coordinateur ni de hass.
"""

from __future__ import annotations

from datetime import date, time, timedelta, timezone

from custom_components.calendrier_scolaire_quebecois.coordinator import (
    build_manual_events,
)
from custom_components.calendrier_scolaire_quebecois.models import (
    EventCategory,
    ManualEvent,
    SchoolEvent,
)

_TZ = timezone(timedelta(hours=-5))
_TODAY = date(2026, 12, 1)


def _conge(premier: date, dernier: date) -> SchoolEvent:
    """Fermeture de source, pour alimenter closed_days."""
    return SchoolEvent(
        summary="Conge",
        start=premier,
        end=dernier + timedelta(days=1),
        category=EventCategory.HOLIDAY,
        source="CSS",
    )


def _regle(**kwargs) -> ManualEvent:
    """Regle manuelle avec des defauts raisonnables."""
    params = {
        "event_id": "x",
        "summary": "Cours",
        "start_date": date(2026, 9, 1),
        "end_date": date(2026, 9, 30),
        "weekdays": (1,),  # mardi
    }
    params.update(kwargs)
    return ManualEvent(**params)


def test_build_sans_regle_ne_produit_rien():
    assert build_manual_events([], [], today=_TODAY, tz=_TZ) == []


def test_build_sans_source_ne_filtre_pas():
    """Sans evenements de source, aucune occurrence n'est retiree."""
    regle = _regle()
    occ = build_manual_events([regle], [], today=_TODAY, tz=_TZ)

    # 5 mardis en septembre 2026 (1, 8, 15, 22, 29).
    assert len(occ) == 5
    assert all(e.source == "manuel" for e in occ)


def test_build_retire_les_jours_fermes_des_sources():
    """Un mardi couvert par un conge de source est retire."""
    # Conge couvrant le mardi 8 septembre.
    sources = [_conge(date(2026, 9, 7), date(2026, 9, 11))]
    occ = build_manual_events([_regle()], sources, today=_TODAY, tz=_TZ)

    jours = [e.first_day for e in occ]
    assert date(2026, 9, 8) not in jours
    assert jours == [
        date(2026, 9, 1),
        date(2026, 9, 15),
        date(2026, 9, 22),
        date(2026, 9, 29),
    ]


def test_build_respecte_skip_closures_faux():
    """Une regle a skip_closures faux conserve ses occurrences malgre le conge."""
    sources = [_conge(date(2026, 9, 7), date(2026, 9, 11))]
    regle = _regle(skip_closures=False)
    occ = build_manual_events([regle], sources, today=_TODAY, tz=_TZ)

    assert date(2026, 9, 8) in [e.first_day for e in occ]


def test_build_filtre_hors_periode_scolaire():
    """Hors des bornes deduites des sources, les occurrences sont retirees."""
    sources = [
        SchoolEvent(
            summary="Rentree",
            start=date(2026, 9, 1),
            end=date(2026, 9, 2),
            category=EventCategory.TERM_START,
            source="CSS",
        ),
        SchoolEvent(
            summary="Fin des classes",
            start=date(2027, 6, 23),
            end=date(2027, 6, 24),
            category=EventCategory.TERM_END,
            source="CSS",
        ),
    ]
    # Regle courant tout l'ete suivant, au-dela de la fin des classes.
    regle = _regle(start_date=date(2027, 6, 1), end_date=date(2027, 7, 31))
    occ = build_manual_events([regle], sources, today=date(2027, 3, 1), tz=_TZ)

    # Seuls les mardis jusqu'au 23 juin inclus sont conserves.
    assert all(e.first_day <= date(2027, 6, 23) for e in occ)
    assert occ  # il en reste (les mardis de juin avant la fin)


def test_build_occurrences_horodatees_localisees():
    """Les heures sont posees dans le fuseau fourni."""
    regle = _regle(
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 1),
        weekdays=(),
        start_time=time(10, 0),
        end_time=time(11, 0),
    )
    occ = build_manual_events([regle], [], today=_TODAY, tz=_TZ)

    assert len(occ) == 1
    assert occ[0].start.tzinfo == _TZ
    assert occ[0].start.hour == 10


def test_build_plusieurs_regles_cumulees():
    """Les occurrences de plusieurs regles sont toutes presentes."""
    lundi = _regle(event_id="a", summary="Lundi", weekdays=(0,))
    jeudi = _regle(event_id="b", summary="Jeudi", weekdays=(3,))
    occ = build_manual_events([lundi, jeudi], [], today=_TODAY, tz=_TZ)

    titres = {e.summary for e in occ}
    assert titres == {"Lundi", "Jeudi"}
