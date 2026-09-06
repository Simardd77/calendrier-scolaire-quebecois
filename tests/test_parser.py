"""Tests unitaires de l'analyse de texte.

L'ancien ParserEngine a ete redecoupe par le refactor: l'extraction de dates
vit dans parsers/dates.py et la construction des evenements dans
parsers/events.py. Les tests ci-dessous conservent l'intention d'origine.
"""

from datetime import date

from custom_components.calendrier_scolaire_quebecois.models import EventCategory
from custom_components.calendrier_scolaire_quebecois.parsers.dates import (
    find_date_spans,
)
from custom_components.calendrier_scolaire_quebecois.parsers.events import (
    extract_events_from_text,
)

# Annee scolaire de reference, utilisee pour deduire les annees absentes.
SCHOOL_YEAR = 2024


def test_parser_extract_dates():
    """Test d'extraction de dates."""
    text = "L'école est fermée le 15/08/2024"

    spans = find_date_spans(text, SCHOOL_YEAR)

    assert len(spans) > 0
    assert spans[0].start.day == 15
    assert spans[0].start.month == 8
    assert spans[0].start.year == 2024
    assert spans[0].is_single_day


def test_parser_extract_events_from_text():
    """Test d'extraction d'événements à partir du texte."""
    text = """
    Calendrier scolaire 2024

    Les cours débutent le 05/09/2024
    Congé : 25/12/2024 - 02/01/2025
    Réunion : 10/10/2024
    """

    events = extract_events_from_text(text, "École Test", SCHOOL_YEAR)

    assert len(events) >= 1
    # La ligne de titre ne porte qu'un millesime: elle ne doit pas produire
    # d'evenement.
    assert len(events) == 3
    assert all(event.source == "École Test" for event in events)


def test_parser_events_sont_tries_et_classes():
    """Chaque ligne datee est classee selon son libelle."""
    text = """
    Les cours débutent le 05/09/2024
    Congé : 25/12/2024 - 02/01/2025
    Réunion : 10/10/2024
    """

    events = extract_events_from_text(text, "École Test", SCHOOL_YEAR)

    assert [event.first_day for event in events] == [
        date(2024, 9, 5),
        date(2024, 10, 10),
        date(2024, 12, 25),
    ]
    assert [event.category for event in events] == [
        EventCategory.EVENT,
        EventCategory.MEETING,
        EventCategory.HOLIDAY,
    ]


def test_parser_conserve_la_plage_du_conge_des_fetes():
    """Le conge des fetes couvre toutes les journees de la plage."""
    events = extract_events_from_text(
        "Congé : 25/12/2024 - 02/01/2025", "École Test", SCHOOL_YEAR
    )

    assert len(events) == 1
    conge = events[0]
    assert conge.first_day == date(2024, 12, 25)
    assert conge.last_day == date(2025, 1, 2)
    assert conge.category is EventCategory.HOLIDAY
    assert conge.closes_school


def test_parser_derive_le_titre_sans_la_date():
    """Le titre retenu est le reste de la ligne, sans la date."""
    events = extract_events_from_text("Réunion : 10/10/2024", "École Test", SCHOOL_YEAR)

    assert len(events) == 1
    assert events[0].summary == "Réunion"
