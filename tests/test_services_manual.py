"""Tests de la validation des services d'evenements manuels.

Le gros de la logique specifique aux services est pur: la conversion des jours
de semaine et le schema voluptuous. On les teste directement, sans monter de
hass. La plomberie Home Assistant (resolution d'entree, async_update_entry) est
du code partage, deja eprouve par les services de sources existants.
"""

from __future__ import annotations

from datetime import date, time

import pytest
import voluptuous as vol

from custom_components.calendrier_scolaire_quebecois import (
    SERVICE_ADD_MANUAL_EVENT_SCHEMA,
    _coerce_weekday,
)

# --- _coerce_weekday ---------------------------------------------------------


@pytest.mark.parametrize(
    ("entree", "attendu"),
    [
        ("lundi", 0),
        ("Mardi", 1),
        ("MERCREDI", 2),
        ("jeudi", 3),
        ("monday", 0),
        ("Sunday", 6),
        (0, 0),
        (6, 6),
        ("0", 0),
        ("5", 5),
    ],
)
def test_coerce_weekday_accepte_noms_et_entiers(entree, attendu):
    assert _coerce_weekday(entree) == attendu


@pytest.mark.parametrize("entree", ["funday", "", 7, -1, "8", True, 1.5])
def test_coerce_weekday_refuse_les_valeurs_invalides(entree):
    with pytest.raises(vol.Invalid):
        _coerce_weekday(entree)


# --- SERVICE_ADD_MANUAL_EVENT_SCHEMA -----------------------------------------


def test_schema_minimal_ponctuel():
    """Un evenement ponctuel ne requiert que titre et dates."""
    data = SERVICE_ADD_MANUAL_EVENT_SCHEMA(
        {
            "summary": "Sortie",
            "start_date": "2026-10-15",
            "end_date": "2026-10-15",
        }
    )
    assert data["summary"] == "Sortie"
    assert data["start_date"] == date(2026, 10, 15)
    assert data["weekdays"] == []  # defaut
    assert data["skip_closures"] is True  # defaut


def test_schema_recurrent_convertit_les_jours():
    """Les jours nommes sont convertis en indices via le schema."""
    data = SERVICE_ADD_MANUAL_EVENT_SCHEMA(
        {
            "summary": "Cours",
            "start_date": "2026-09-01",
            "end_date": "2027-06-23",
            "weekdays": ["mardi", "jeudi"],
            "start_time": "10:00:00",
            "end_time": "11:00:00",
        }
    )
    assert data["weekdays"] == [1, 3]
    assert data["start_time"] == time(10, 0)
    assert data["end_time"] == time(11, 0)


def test_schema_jour_unique_non_liste():
    """Un jour fourni seul est accepte et normalise en liste."""
    data = SERVICE_ADD_MANUAL_EVENT_SCHEMA(
        {
            "summary": "Cours",
            "start_date": "2026-09-01",
            "end_date": "2026-09-30",
            "weekdays": "vendredi",
        }
    )
    assert data["weekdays"] == [4]


def test_schema_refuse_titre_manquant():
    with pytest.raises(vol.Invalid):
        SERVICE_ADD_MANUAL_EVENT_SCHEMA(
            {"start_date": "2026-09-01", "end_date": "2026-09-01"}
        )


def test_schema_refuse_jour_invalide():
    with pytest.raises(vol.Invalid):
        SERVICE_ADD_MANUAL_EVENT_SCHEMA(
            {
                "summary": "Cours",
                "start_date": "2026-09-01",
                "end_date": "2026-09-30",
                "weekdays": ["funday"],
            }
        )
