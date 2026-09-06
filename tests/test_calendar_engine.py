"""Tests unitaires de l'agrégation du calendrier.

Le CalendarEngine a ete remplace par CalendarData, produit a chaque cycle du
coordinateur. Le regroupement en un calendrier par source a disparu: les
evenements sont desormais distingues par leur categorie. Les tests conservent
l'intention d'origine (separer les conges, lister les evenements a venir).
"""

from datetime import timedelta

import homeassistant.util.dt as dt_util

from custom_components.calendrier_scolaire_quebecois.coordinator import CalendarData
from custom_components.calendrier_scolaire_quebecois.models import EventCategory


def test_calendar_organize_events(make_event):
    """Test de l'organisation des événements."""
    today = dt_util.now().date()

    cours = make_event("Cours", today, category=EventCategory.EVENT, source="École A")
    conge = make_event("Congé", today, category=EventCategory.HOLIDAY, source="École B")

    data = CalendarData(events=[cours, conge], sources_total=2)

    du_jour = data.events_on(today)

    assert len(du_jour) == 2
    # Le conge est distingue par sa categorie, non plus par un calendrier dedie.
    fermetures = [event for event in du_jour if event.closes_school]
    assert [event.summary for event in fermetures] == ["Congé"]


def test_calendar_get_upcoming_events(make_event):
    """Test de récupération des événements à venir."""
    today = dt_util.now().date()

    aujourdhui = make_event("Aujourd'hui", today)
    semaine_prochaine = make_event("La semaine prochaine", today + timedelta(days=7))
    plus_tard = make_event("Bien plus tard", today + timedelta(days=30))

    data = CalendarData(
        events=[aujourdhui, semaine_prochaine, plus_tard], sources_total=1
    )

    debut = dt_util.start_of_local_day(today)
    upcoming = data.events_between(debut, debut + timedelta(days=7))

    assert len(upcoming) >= 1
    assert [event.summary for event in upcoming] == ["Aujourd'hui"]
    assert "Bien plus tard" not in [event.summary for event in upcoming]


def test_events_between_est_trie_par_debut(make_event):
    """La periode est rendue dans l'ordre chronologique."""
    today = dt_util.now().date()

    data = CalendarData(
        events=[
            make_event("Dans trois jours", today + timedelta(days=3)),
            make_event("Demain", today + timedelta(days=1)),
        ],
        sources_total=1,
    )

    debut = dt_util.start_of_local_day(today)
    resultat = data.events_between(debut, debut + timedelta(days=10))

    assert [event.summary for event in resultat] == ["Demain", "Dans trois jours"]


def test_events_on_ignore_les_journees_non_couvertes(make_event):
    """Une journee hors plage ne retourne aucun evenement."""
    today = dt_util.now().date()

    relache = make_event(
        "Relâche", today + timedelta(days=10), days=5, category=EventCategory.HOLIDAY
    )
    data = CalendarData(events=[relache], sources_total=1)

    assert data.events_on(today) == []
    assert data.events_on(today + timedelta(days=10)) == [relache]
    assert data.events_on(today + timedelta(days=14)) == [relache]
    assert data.events_on(today + timedelta(days=15)) == []


def test_next_event_retourne_l_evenement_en_cours(make_event):
    """Un evenement en cours est plus pertinent que le suivant."""
    today = dt_util.now().date()

    en_cours = make_event("En cours", today, days=3)
    suivant = make_event("Suivant", today + timedelta(days=10))

    data = CalendarData(events=[suivant, en_cours], sources_total=1)

    assert data.next_event(dt_util.start_of_local_day(today)) is en_cours


def test_next_event_sans_evenement_futur(make_event):
    """Sans evenement a venir, aucun n'est retourne."""
    today = dt_util.now().date()

    passe = make_event("Terminé", today - timedelta(days=30))
    data = CalendarData(events=[passe], sources_total=1)

    assert data.next_event(dt_util.start_of_local_day(today)) is None


def test_is_within_term(make_event):
    """La periode scolaire se deduit des bornes annoncees par le document."""
    today = dt_util.now().date()

    data = CalendarData(
        events=[
            make_event(
                "Rentrée",
                today - timedelta(days=10),
                category=EventCategory.TERM_START,
            ),
            make_event(
                "Fin des classes",
                today + timedelta(days=100),
                category=EventCategory.TERM_END,
            ),
        ],
        sources_total=1,
    )

    assert data.is_within_term(today) is True
    assert data.is_within_term(today + timedelta(days=200)) is False


def test_is_within_term_indetermine_sans_bornes(make_event):
    """Sans rentree ni fin annoncee, la question reste ouverte."""
    today = dt_util.now().date()
    data = CalendarData(events=[make_event("Photo", today)], sources_total=1)

    assert data.is_within_term(today) is None


def test_sources_ok_compte_les_sources_sans_erreur():
    """Le compte des sources saines sert au diagnostic de l'integration."""
    data = CalendarData(sources_total=3, source_errors={"École B": "HTTP 404"})

    assert data.sources_ok == 2


def test_sources_ok_ne_devient_jamais_negatif():
    """Plus d'erreurs que de sources ne doit pas produire un compte negatif."""
    data = CalendarData(sources_total=1, source_errors={"A": "x", "B": "y"})

    assert data.sources_ok == 0
