"""Ajouter ou retirer un evenement manuel ne recharge pas l'integration.

Un rechargement retelecharge les sources et rend l'entite indisponible. La vue
des calendriers redemande ses evenements des qu'elle vient d'ajouter ou de
supprimer un evenement: elle recevait alors une erreur pendant ce temps.
"""

from __future__ import annotations

import asyncio
from datetime import date, time

from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.calendrier_scolaire_quebecois import coordinator as coord
from custom_components.calendrier_scolaire_quebecois.const import (
    CONF_MANUAL_EVENTS,
    CONF_REFRESH_INTERVAL,
    CONF_SOURCES,
    DOMAIN,
)
from custom_components.calendrier_scolaire_quebecois.models import ManualEvent

ENTITY_ID = "calendar.calendrier_scolaire"
URL = f"/api/calendars/{ENTITY_ID}?start=2026-11-01T00:00:00Z&end=2026-12-31T00:00:00Z"
SOURCE = {
    "id": "src1",
    "name": "Source de test",
    "url": "https://exemple.test/calendrier.pdf",
    "type": "direct_url",
}


def _serie() -> ManualEvent:
    return ManualEvent(
        event_id="serie1",
        summary="Éducation physique",
        start_date=date(2026, 11, 16),
        end_date=date(2026, 11, 30),
        weekdays=(0,),
        start_time=time(14, 0),
        end_time=time(15, 0),
    )


class _Espion:
    """Compte les cycles de mise a jour et simule un telechargement lent."""

    def __init__(self, monkeypatch, *, source_en_echec: bool = False) -> None:
        self.cycles = 0
        self.delai = 0.0
        original = coord.SchoolCalendarCoordinator._async_update_data
        espion = self

        async def update(coordinator):
            espion.cycles += 1
            if espion.delai:
                await asyncio.sleep(espion.delai)
            return await original(coordinator)

        monkeypatch.setattr(
            coord.SchoolCalendarCoordinator, "_async_update_data", update
        )
        if source_en_echec:

            async def echec(coordinator, source):
                raise coord.FetchError("hors ligne")

            monkeypatch.setattr(
                coord.SchoolCalendarCoordinator, "_async_load_source", echec
            )


async def _setup(hass, *, sources=(), rules=()) -> MockConfigEntry:
    await hass.config.async_set_time_zone("America/Toronto")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Calendrier scolaire",
        data={"name": "Calendrier scolaire"},
        options={
            CONF_SOURCES: list(sources),
            CONF_MANUAL_EVENTS: [rule.as_dict() for rule in rules],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _creer_par_la_vue(ws) -> dict:
    await ws.send_json_auto_id(
        {
            "type": "calendar/event/create",
            "entity_id": ENTITY_ID,
            "event": {
                "summary": "Test",
                "dtstart": "2026-11-16T14:00:00-05:00",
                "dtend": "2026-11-16T15:00:00-05:00",
            },
        }
    )
    return await ws.receive_json()


async def test_l_ajout_ne_recharge_pas_et_la_vue_repond_aussitot(
    hass, hass_ws_client, hass_client, enable_custom_integrations, monkeypatch
):
    espion = _Espion(monkeypatch)
    entry = await _setup(hass)
    coordinateur = entry.runtime_data
    entite = hass.data["calendar"].get_entity(ENTITY_ID)
    ws = await hass_ws_client()
    http = await hass_client()

    espion.cycles = 0
    espion.delai = 1.0  # un rechargement durerait une seconde, comme les PDF
    reponse = await _creer_par_la_vue(ws)
    assert reponse["success"], reponse

    # Aussitot apres la reponse, comme le fait la vue des calendriers.
    pendant = await http.get(URL)
    assert pendant.status == 200
    assert "Test" in await pendant.text()

    await hass.async_block_till_done()
    assert espion.cycles == 0, "les sources ont ete retelechargees"
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is coordinateur
    assert hass.data["calendar"].get_entity(ENTITY_ID) is entite
    assert hass.states.get(ENTITY_ID).attributes["events_count"] == 1


async def test_la_suppression_ne_recharge_pas(
    hass, hass_ws_client, hass_client, enable_custom_integrations, monkeypatch
):
    espion = _Espion(monkeypatch)
    entry = await _setup(hass, rules=[_serie()])
    coordinateur = entry.runtime_data
    ws = await hass_ws_client()
    http = await hass_client()

    espion.cycles = 0
    espion.delai = 1.0
    await ws.send_json_auto_id(
        {
            "type": "calendar/event/delete",
            "entity_id": ENTITY_ID,
            "uid": "serie1",
            "recurrence_id": "2026-11-23",
        }
    )
    assert (await ws.receive_json())["success"]

    pendant = await http.get(URL)
    assert pendant.status == 200

    await hass.async_block_till_done()
    assert espion.cycles == 0
    assert entry.runtime_data is coordinateur
    assert hass.states.get(ENTITY_ID).attributes["events_count"] == 2


async def test_les_sources_gardent_leurs_evenements_apres_un_ajout(
    hass, hass_ws_client, enable_custom_integrations, monkeypatch
):
    """Le recalcul repart des sources deja lues, sans les perdre."""
    _Espion(monkeypatch)
    entry = await _setup(hass, rules=[_serie()])
    coordinateur = entry.runtime_data
    avant = [e for e in coordinateur.data.events if e.source != "manuel"]

    ws = await hass_ws_client()
    assert (await _creer_par_la_vue(ws))["success"]
    await hass.async_block_till_done()

    apres = [e for e in coordinateur.data.events if e.source != "manuel"]
    assert apres == avant
    assert len(coordinateur.data.events) == 4  # 3 lundis + 1 ponctuel


async def test_un_autre_reglage_recharge_toujours(
    hass, enable_custom_integrations, monkeypatch
):
    espion = _Espion(monkeypatch)
    entry = await _setup(hass, rules=[_serie()])
    ancien = entry.runtime_data
    espion.cycles = 0

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_REFRESH_INTERVAL: 7200}
    )
    await hass.async_block_till_done()

    assert entry.runtime_data is not ancien
    assert espion.cycles == 1


async def test_changer_les_sources_recharge_toujours(
    hass, enable_custom_integrations, monkeypatch
):
    espion = _Espion(monkeypatch, source_en_echec=True)
    entry = await _setup(hass, rules=[_serie()])
    ancien = entry.runtime_data
    espion.cycles = 0

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_SOURCES: [SOURCE]}
    )
    await hass.async_block_till_done()

    assert entry.runtime_data is not ancien
    assert espion.cycles == 1


async def test_changer_le_secret_du_flux_recharge_toujours(
    hass, enable_custom_integrations, monkeypatch
):
    espion = _Espion(monkeypatch)
    entry = await _setup(hass, rules=[_serie()])
    ancien = entry.runtime_data
    espion.cycles = 0

    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "feed_secret": "x"}
    )
    await hass.async_block_till_done()

    assert entry.runtime_data is not ancien


async def test_plus_de_source_ni_d_evenement_manuel_recharge(
    hass, enable_custom_integrations, monkeypatch
):
    """Toutes les sources en echec et le dernier evenement manuel retire.

    Le recalcul ne peut rien afficher: l'integration se recharge pour relancer
    les telechargements, au lieu de laisser un calendrier vide en erreur.
    """
    espion = _Espion(monkeypatch, source_en_echec=True)
    entry = await _setup(hass, sources=[SOURCE], rules=[_serie()])
    ancien = entry.runtime_data
    espion.cycles = 0

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_MANUAL_EVENTS: []}
    )
    await hass.async_block_till_done()

    assert entry.runtime_data is not ancien
    assert espion.cycles == 1


async def test_indicateur_de_changement_limite_aux_evenements_manuels(
    hass, enable_custom_integrations, monkeypatch
):
    _Espion(monkeypatch)
    entry = await _setup(hass, rules=[_serie()])
    coordinateur = entry.runtime_data
    assert coordinateur.only_manual_events_changed

    # Une modification des sources n'est pas "seulement les evenements manuels".
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_SOURCES: [SOURCE]}
    )
    assert not coordinateur.only_manual_events_changed
