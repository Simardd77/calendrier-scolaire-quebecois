"""Creation d'un evenement depuis la vue des calendriers, par l'integration reelle.

Le service ``calendar.create_event`` de Home Assistant et le bouton d'ajout de
l'interface appellent la meme methode ``async_create_event`` de l'entite.
"""

from __future__ import annotations

import pytest
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.calendrier_scolaire_quebecois.const import (
    CONF_MANUAL_EVENTS,
    CONF_SOURCES,
    DOMAIN,
)

ENTITY_ID = "calendar.calendrier_scolaire"


async def _setup(hass, enable_custom_integrations) -> MockConfigEntry:
    # Le fuseau de test de Home Assistant est US/Pacific: on se place a Montreal.
    await hass.config.async_set_time_zone("America/Toronto")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Calendrier scolaire",
        data={"name": "Calendrier scolaire"},
        options={CONF_SOURCES: []},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_l_entite_declare_la_creation(hass, enable_custom_integrations):
    from homeassistant.components.calendar import CalendarEntityFeature

    await _setup(hass, enable_custom_integrations)
    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.attributes["supported_features"] & CalendarEntityFeature.CREATE_EVENT


async def test_creation_d_un_evenement_horodate(hass, enable_custom_integrations):
    entry = await _setup(hass, enable_custom_integrations)

    await hass.services.async_call(
        "calendar",
        "create_event",
        {
            "entity_id": ENTITY_ID,
            "summary": "Éducation physique",
            "start_date_time": "2026-11-16 14:00:00",
            "end_date_time": "2026-11-16 15:00:00",
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    stored = entry.options[CONF_MANUAL_EVENTS]
    assert len(stored) == 1
    assert stored[0]["summary"] == "Éducation physique"
    assert stored[0]["start_date"] == "2026-11-16"
    assert stored[0]["start_time"] == "14:00"
    assert stored[0]["end_time"] == "15:00"
    assert stored[0]["weekdays"] == []
    assert stored[0]["skip_closures"] is True


async def test_creation_d_une_journee_entiere(hass, enable_custom_integrations):
    entry = await _setup(hass, enable_custom_integrations)

    await hass.services.async_call(
        "calendar",
        "create_event",
        {
            "entity_id": ENTITY_ID,
            "summary": "Sortie",
            "start_date": "2026-11-16",
            "end_date": "2026-11-17",
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    stored = entry.options[CONF_MANUAL_EVENTS]
    assert len(stored) == 1
    assert "start_time" not in stored[0]


async def test_creation_refusee_message_clair(hass, enable_custom_integrations):
    """Un evenement non representable est refuse avec un message lisible."""
    entry = await _setup(hass, enable_custom_integrations)

    with pytest.raises(HomeAssistantError, match="plusieurs jours"):
        await hass.services.async_call(
            "calendar",
            "create_event",
            {
                "entity_id": ENTITY_ID,
                "summary": "Camp",
                "start_date": "2026-11-16",
                "end_date": "2026-11-30",
            },
            blocking=True,
        )
    assert not entry.options.get(CONF_MANUAL_EVENTS)


async def test_doublon_refuse(hass, enable_custom_integrations):
    entry = await _setup(hass, enable_custom_integrations)
    data = {
        "entity_id": ENTITY_ID,
        "summary": "Sortie",
        "start_date": "2026-11-16",
        "end_date": "2026-11-17",
    }
    await hass.services.async_call("calendar", "create_event", data, blocking=True)
    await hass.async_block_till_done()

    with pytest.raises(HomeAssistantError, match="identique"):
        await hass.services.async_call("calendar", "create_event", data, blocking=True)
    assert len(entry.options[CONF_MANUAL_EVENTS]) == 1


async def _create_ws(hass_ws_client, event: dict) -> dict:
    client = await hass_ws_client()
    await client.send_json_auto_id(
        {"type": "calendar/event/create", "entity_id": ENTITY_ID, "event": event}
    )
    return await client.receive_json()


async def test_creation_recurrente_par_la_vue_des_calendriers(
    hass, hass_ws_client, enable_custom_integrations
):
    """Le 16 au 30 novembre, le lundi, de 14 h a 15 h."""
    entry = await _setup(hass, enable_custom_integrations)

    response = await _create_ws(
        hass_ws_client,
        {
            "summary": "Éducation physique",
            "dtstart": "2026-11-16T14:00:00-05:00",
            "dtend": "2026-11-16T15:00:00-05:00",
            "rrule": "FREQ=WEEKLY;BYDAY=MO;UNTIL=20261130",
        },
    )
    assert response["success"], response
    await hass.async_block_till_done()

    stored = entry.options[CONF_MANUAL_EVENTS]
    assert len(stored) == 1
    assert stored[0]["weekdays"] == [0]
    assert stored[0]["start_date"] == "2026-11-16"
    assert stored[0]["end_date"] == "2026-11-30"
    assert stored[0]["start_time"] == "14:00"
    assert stored[0]["end_time"] == "15:00"


async def test_repetition_non_prise_en_charge_signalee_a_l_interface(
    hass, hass_ws_client, enable_custom_integrations
):
    entry = await _setup(hass, enable_custom_integrations)

    response = await _create_ws(
        hass_ws_client,
        {
            "summary": "Chorale",
            "dtstart": "2026-11-16T14:00:00-05:00",
            "dtend": "2026-11-16T15:00:00-05:00",
            "rrule": "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO;COUNT=4",
        },
    )
    assert response["success"] is False
    assert "une semaine sur deux" in response["error"]["message"]
    assert not entry.options.get(CONF_MANUAL_EVENTS)
