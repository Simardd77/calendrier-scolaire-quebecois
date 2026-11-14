"""Suppression depuis la vue des calendriers, par l'integration reelle.

Les tests passent par la commande WebSocket ``calendar/event/delete``, celle que
l'interface utilise.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest
from homeassistant.components.calendar import CalendarEntityFeature
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.calendrier_scolaire_quebecois.const import (
    CONF_MANUAL_EVENTS,
    CONF_SOURCES,
    DOMAIN,
)
from custom_components.calendrier_scolaire_quebecois.models import ManualEvent

ENTITY_ID = "calendar.calendrier_scolaire"


def _serie() -> ManualEvent:
    """Le lundi 16, 23 et 30 novembre 2026, de 14 h a 15 h."""
    return ManualEvent(
        event_id="serie1",
        summary="Éducation physique",
        start_date=date(2026, 11, 16),
        end_date=date(2026, 11, 30),
        weekdays=(0,),
        start_time=time(14, 0),
        end_time=time(15, 0),
    )


def _ponctuel() -> ManualEvent:
    return ManualEvent(
        event_id="ponctuel1",
        summary="Sortie",
        start_date=date(2026, 11, 18),
        end_date=date(2026, 11, 18),
    )


async def _setup(hass, *rules: ManualEvent) -> MockConfigEntry:
    await hass.config.async_set_time_zone("America/Toronto")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Calendrier scolaire",
        data={"name": "Calendrier scolaire"},
        options={
            CONF_SOURCES: [],
            CONF_MANUAL_EVENTS: [rule.as_dict() for rule in rules],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _delete(hass, hass_ws_client, uid, recurrence_id=None, plage=None) -> dict:
    message = {
        "type": "calendar/event/delete",
        "entity_id": ENTITY_ID,
        "uid": uid,
    }
    if recurrence_id is not None:
        message["recurrence_id"] = recurrence_id
    if plage is not None:
        message["recurrence_range"] = plage
    client = await hass_ws_client()
    await client.send_json_auto_id(message)
    response = await client.receive_json()
    await hass.async_block_till_done()
    return response


async def _jours_affiches(hass) -> list[str]:
    """Journees (AAAA-MM-JJ) affichees par la vue pour novembre 2026."""
    entity = hass.data["calendar"].get_entity(ENTITY_ID)
    debut = dt_util.as_local(datetime(2026, 11, 1))
    fin = debut + timedelta(days=40)
    evenements = await entity.async_get_events(hass, debut, fin)
    return sorted(event.start.date().isoformat() for event in evenements)


def _regles(entry) -> list[dict]:
    return entry.options.get(CONF_MANUAL_EVENTS) or []


async def test_l_entite_declare_la_suppression(hass, enable_custom_integrations):
    await _setup(hass, _serie())
    fonctions = hass.states.get(ENTITY_ID).attributes["supported_features"]
    assert fonctions & CalendarEntityFeature.DELETE_EVENT
    assert fonctions & CalendarEntityFeature.CREATE_EVENT


async def test_la_vue_recoit_la_serie(hass, enable_custom_integrations):
    await _setup(hass, _serie())
    entity = hass.data["calendar"].get_entity(ENTITY_ID)
    debut = dt_util.as_local(datetime(2026, 11, 1))
    evenements = await entity.async_get_events(hass, debut, debut + timedelta(days=40))
    assert [event.uid for event in evenements] == ["serie1"] * 3
    assert [event.recurrence_id for event in evenements] == [
        "2026-11-16",
        "2026-11-23",
        "2026-11-30",
    ]
    assert all(event.rrule for event in evenements)


async def test_supprimer_un_evenement_ponctuel(
    hass, hass_ws_client, enable_custom_integrations
):
    entry = await _setup(hass, _serie(), _ponctuel())

    reponse = await _delete(hass, hass_ws_client, "ponctuel1")

    assert reponse["success"], reponse
    assert [item["id"] for item in _regles(entry)] == ["serie1"]


async def test_supprimer_une_seule_occurrence(
    hass, hass_ws_client, enable_custom_integrations
):
    entry = await _setup(hass, _serie())

    reponse = await _delete(hass, hass_ws_client, "serie1", "2026-11-23")

    assert reponse["success"], reponse
    assert _regles(entry)[0]["excluded_dates"] == ["2026-11-23"]
    assert await _jours_affiches(hass) == ["2026-11-16", "2026-11-30"]


async def test_supprimer_celui_ci_et_les_suivants(
    hass, hass_ws_client, enable_custom_integrations
):
    entry = await _setup(hass, _serie())

    reponse = await _delete(
        hass, hass_ws_client, "serie1", "2026-11-23", "THISANDFUTURE"
    )

    assert reponse["success"], reponse
    assert _regles(entry)[0]["end_date"] == "2026-11-22"
    assert await _jours_affiches(hass) == ["2026-11-16"]


async def test_supprimer_toute_la_serie_depuis_la_premiere_occurrence(
    hass, hass_ws_client, enable_custom_integrations
):
    entry = await _setup(hass, _serie(), _ponctuel())

    reponse = await _delete(
        hass, hass_ws_client, "serie1", "2026-11-16", "THISANDFUTURE"
    )

    assert reponse["success"], reponse
    assert [item["id"] for item in _regles(entry)] == ["ponctuel1"]


async def test_un_evenement_de_source_n_est_pas_supprimable(
    hass, hass_ws_client, enable_custom_integrations
):
    entry = await _setup(hass, _serie())

    reponse = await _delete(hass, hass_ws_client, "uid-d-une-source")

    assert reponse["success"] is False
    assert "Seuls les evenements manuels" in reponse["error"]["message"]
    assert len(_regles(entry)) == 1


async def test_une_occurrence_deja_retiree_est_refusee(
    hass, hass_ws_client, enable_custom_integrations
):
    entry = await _setup(hass, _serie())
    await _delete(hass, hass_ws_client, "serie1", "2026-11-23")

    reponse = await _delete(hass, hass_ws_client, "serie1", "2026-11-23")

    assert reponse["success"] is False
    assert "n'existe plus" in reponse["error"]["message"]
    assert _regles(entry)[0]["excluded_dates"] == ["2026-11-23"]


def _huit_lundis() -> ManualEvent:
    """Les lundis du 16 novembre 2026 au 4 janvier 2027: 8 occurrences."""
    return ManualEvent(
        event_id="huit1",
        summary="Chorale",
        start_date=date(2026, 11, 16),
        end_date=date(2027, 1, 4),
        weekdays=(0,),
        start_time=time(14, 0),
        end_time=time(15, 0),
    )


async def _evenements_de_la_vue(hass):
    entity = hass.data["calendar"].get_entity(ENTITY_ID)
    debut = dt_util.as_local(datetime(2026, 11, 1))
    return await entity.async_get_events(hass, debut, debut + timedelta(days=90))


async def test_serie_de_huit_reduite_a_une_occurrence(
    hass, hass_ws_client, enable_custom_integrations
):
    """Supprimer a partir de la 2e, puis il ne reste qu'un evenement ordinaire."""
    entry = await _setup(hass, _huit_lundis())
    assert len(await _evenements_de_la_vue(hass)) == 8

    # A partir de la 2e occurrence (23 novembre), jusqu'a la fin.
    reponse = await _delete(
        hass, hass_ws_client, "huit1", "2026-11-23", "THISANDFUTURE"
    )
    assert reponse["success"], reponse

    (reste,) = await _evenements_de_la_vue(hass)
    assert reste.start.date().isoformat() == "2026-11-16"
    # Plus de serie: la vue n'a rien a proposer au-dela d'un evenement ordinaire.
    assert reste.recurrence_id is None
    assert reste.rrule is None

    # Comme l'interface pour un evenement ordinaire: uid seul, sans recurrence_id.
    reponse = await _delete(hass, hass_ws_client, "huit1")
    assert reponse["success"], reponse
    assert not _regles(entry)
    assert await _evenements_de_la_vue(hass) == []


async def test_serie_reduite_a_une_occurrence_par_exclusions(
    hass, hass_ws_client, enable_custom_integrations
):
    """Trois lundis, deux supprimes un a un: le dernier devient ordinaire."""
    await _setup(hass, _serie())
    await _delete(hass, hass_ws_client, "serie1", "2026-11-16")
    avant = await _evenements_de_la_vue(hass)
    assert len(avant) == 2
    assert all(event.rrule for event in avant)  # deux restantes: encore une serie

    await _delete(hass, hass_ws_client, "serie1", "2026-11-23")

    (reste,) = await _evenements_de_la_vue(hass)
    assert reste.start.date().isoformat() == "2026-11-30"
    assert reste.recurrence_id is None
    assert reste.rrule is None
