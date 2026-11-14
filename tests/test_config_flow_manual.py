"""Tests de la saisie des evenements manuels dans le flux d'options.

Les fonctions pures (construction de la regle depuis le formulaire, libelle de
la liste de retrait) sont testees directement. La plomberie du flux est du code
partage avec les etapes de sources.
"""

from __future__ import annotations

from datetime import date, time

import pytest

from custom_components.calendrier_scolaire_quebecois.config_flow import (
    _MANUAL_EVENT_SCHEMA,
    _build_manual_rule,
    _describe_manual_event,
)


def _form(**overrides):
    data = {
        "summary": "Éducation physique",
        "start_date": "2026-09-01",
        "end_date": "2027-06-23",
        "weekdays": ["1", "3"],
        "start_time": "10:00:00",
        "end_time": "11:00:00",
        "skip_closures": True,
    }
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not None}


def test_regle_recurrente_horodatee():
    rule, error = _build_manual_rule(_form())
    assert error is None
    assert rule.summary == "Éducation physique"
    assert rule.weekdays == (1, 3)
    assert rule.start_date == date(2026, 9, 1)
    assert rule.end_date == date(2027, 6, 23)
    assert rule.start_time == time(10, 0)
    assert rule.end_time == time(11, 0)
    assert rule.skip_closures is True


def test_ponctuel_sans_date_de_fin_ni_heures():
    rule, error = _build_manual_rule(
        _form(end_date=None, weekdays=[], start_time=None, end_time=None)
    )
    assert error is None
    assert rule.end_date == rule.start_date
    assert not rule.is_recurring
    assert rule.all_day


def test_jours_dedoublonnes_et_tries():
    rule, _ = _build_manual_rule(_form(weekdays=["3", "1", "3"]))
    assert rule.weekdays == (1, 3)


def test_identifiant_identique_a_celui_du_service():
    """Meme saisie par le formulaire ou par le service: meme identifiant."""
    from custom_components.calendrier_scolaire_quebecois.models import (
        build_manual_event_id,
    )

    rule, _ = _build_manual_rule(_form())
    assert rule.event_id == build_manual_event_id(
        "Éducation physique", date(2026, 9, 1), (1, 3), time(10, 0)
    )


@pytest.mark.parametrize(
    ("overrides", "erreur"),
    [
        ({"summary": "   "}, "manual_event_summary_required"),
        ({"start_date": "pas-une-date"}, "manual_event_invalid"),
        ({"end_date": "2026-08-01"}, "manual_event_range"),
        ({"end_time": None}, "manual_event_times_together"),
        ({"start_time": None}, "manual_event_times_together"),
        (
            {"start_time": "11:00:00", "end_time": "10:00:00"},
            "manual_event_times_order",
        ),
        (
            {"start_time": "10:00:00", "end_time": "10:00:00"},
            "manual_event_times_order",
        ),
        ({"start_time": "dix heures"}, "manual_event_invalid"),
    ],
)
def test_saisies_refusees(overrides, erreur):
    rule, error = _build_manual_rule(_form(**overrides))
    assert rule is None
    assert error == erreur


def test_schema_valeurs_par_defaut():
    data = _MANUAL_EVENT_SCHEMA({"summary": "Sortie", "start_date": "2026-10-15"})
    assert data["weekdays"] == []
    assert data["skip_closures"] is True


def test_libelle_recurrent():
    rule, _ = _build_manual_rule(_form())
    label = _describe_manual_event(rule.as_dict())
    assert "Éducation physique" in label
    assert "mar., jeu." in label
    assert "10:00-11:00" in label
    assert "2026-09-01 > 2027-06-23" in label


def test_libelle_ponctuel():
    rule, _ = _build_manual_rule(
        _form(weekdays=[], start_time=None, end_time=None, end_date=None)
    )
    assert _describe_manual_event(rule.as_dict()) == "Éducation physique (2026-09-01)"


# --- Flux complet -------------------------------------------------------------


async def test_flux_ajout_puis_retrait(hass, enable_custom_integrations):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.calendrier_scolaire_quebecois.const import (
        CONF_MANUAL_EVENTS,
        DOMAIN,
    )

    entry = MockConfigEntry(domain=DOMAIN, data={"name": "T"}, options={})
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "add_manual_event" in result["menu_options"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_manual_event"}
    )
    assert result["type"] == "form"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _form()
    )
    assert result["type"] == "create_entry"
    stored = entry.options[CONF_MANUAL_EVENTS]
    assert len(stored) == 1
    assert stored[0]["weekdays"] == [1, 3]

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "remove_manual_event"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"manual_events": [stored[0]["id"]]}
    )
    assert result["type"] == "create_entry"
    assert entry.options[CONF_MANUAL_EVENTS] == []


# --- Modification -------------------------------------------------------------


def test_valeurs_de_formulaire_depuis_une_regle_stockee():
    from custom_components.calendrier_scolaire_quebecois.config_flow import (
        _form_values,
    )

    rule, _ = _build_manual_rule(_form())
    values = _form_values(rule.as_dict())
    assert values["weekdays"] == ["1", "3"]
    assert values["start_time"] == "10:00"
    assert values["end_time"] == "11:00"
    # Round-trip: les valeurs reproduisent la meme regle.
    again, error = _build_manual_rule(values)
    assert error is None
    assert again == rule


def test_valeurs_de_formulaire_sans_heures():
    from custom_components.calendrier_scolaire_quebecois.config_flow import (
        _form_values,
    )

    rule, _ = _build_manual_rule(_form(start_time=None, end_time=None))
    values = _form_values(rule.as_dict())
    assert "start_time" not in values
    assert "end_time" not in values


async def test_flux_modification(hass, enable_custom_integrations):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.calendrier_scolaire_quebecois.const import (
        CONF_MANUAL_EVENTS,
        DOMAIN,
    )

    original, _ = _build_manual_rule(_form())
    autre, _ = _build_manual_rule(_form(summary="Chorale", weekdays=["0"]))
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "T"},
        options={CONF_MANUAL_EVENTS: [original.as_dict(), autre.as_dict()]},
    )
    entry.add_to_hass(hass)

    flow = hass.config_entries.options
    result = await flow.async_init(entry.entry_id)
    assert "edit_manual_event" in result["menu_options"]
    result = await flow.async_configure(
        result["flow_id"], {"next_step_id": "edit_manual_event"}
    )
    assert result["type"] == "form"
    result = await flow.async_configure(
        result["flow_id"], {"manual_event": original.event_id}
    )
    # Formulaire prerempli avec les valeurs actuelles.
    assert result["step_id"] == "update_manual_event"
    suggested = {
        str(key): key.description["suggested_value"]
        for key in result["data_schema"].schema
        if key.description and "suggested_value" in key.description
    }
    assert suggested["summary"] == "Éducation physique"
    assert suggested["weekdays"] == ["1", "3"]
    assert suggested["start_time"] == "10:00"

    result = await flow.async_configure(
        result["flow_id"],
        _form(
            summary="EPS", weekdays=["1"], start_time="09:00:00", end_time="10:00:00"
        ),
    )
    assert result["type"] == "create_entry"
    stored = entry.options[CONF_MANUAL_EVENTS]
    assert len(stored) == 2
    assert stored[1] == autre.as_dict()
    assert stored[0]["summary"] == "EPS"
    assert stored[0]["weekdays"] == [1]
    assert stored[0]["start_time"] == "09:00"
    # L'identifiant suit le contenu, l'ancien disparait.
    assert stored[0]["id"] != original.event_id
    assert all(item["id"] != original.event_id for item in stored)


async def test_modification_refuse_un_doublon(hass, enable_custom_integrations):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.calendrier_scolaire_quebecois.const import (
        CONF_MANUAL_EVENTS,
        DOMAIN,
    )

    original, _ = _build_manual_rule(_form())
    autre, _ = _build_manual_rule(_form(summary="Chorale", weekdays=["0"]))
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "T"},
        options={CONF_MANUAL_EVENTS: [original.as_dict(), autre.as_dict()]},
    )
    entry.add_to_hass(hass)

    flow = hass.config_entries.options
    result = await flow.async_init(entry.entry_id)
    result = await flow.async_configure(
        result["flow_id"], {"next_step_id": "edit_manual_event"}
    )
    result = await flow.async_configure(
        result["flow_id"], {"manual_event": autre.event_id}
    )
    # "Chorale" devient identique a l'evenement d'origine.
    result = await flow.async_configure(result["flow_id"], _form())
    assert result["type"] == "form"
    assert result["errors"] == {"base": "manual_event_exists"}
    assert entry.options[CONF_MANUAL_EVENTS] == [original.as_dict(), autre.as_dict()]


async def test_modification_sans_changement_est_acceptee(
    hass, enable_custom_integrations
):
    """Resoumettre l'evenement tel quel ne doit pas etre pris pour un doublon."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.calendrier_scolaire_quebecois.const import (
        CONF_MANUAL_EVENTS,
        DOMAIN,
    )

    original, _ = _build_manual_rule(_form())
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "T"},
        options={CONF_MANUAL_EVENTS: [original.as_dict()]},
    )
    entry.add_to_hass(hass)

    flow = hass.config_entries.options
    result = await flow.async_init(entry.entry_id)
    result = await flow.async_configure(
        result["flow_id"], {"next_step_id": "edit_manual_event"}
    )
    result = await flow.async_configure(
        result["flow_id"], {"manual_event": original.event_id}
    )
    result = await flow.async_configure(result["flow_id"], _form())
    assert result["type"] == "create_entry"
    assert entry.options[CONF_MANUAL_EVENTS] == [original.as_dict()]


async def test_modification_sans_evenement_abandonne(hass, enable_custom_integrations):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.calendrier_scolaire_quebecois.const import DOMAIN

    entry = MockConfigEntry(domain=DOMAIN, data={"name": "T"}, options={})
    entry.add_to_hass(hass)
    flow = hass.config_entries.options
    result = await flow.async_init(entry.entry_id)
    result = await flow.async_configure(
        result["flow_id"], {"next_step_id": "edit_manual_event"}
    )
    assert result["type"] == "abort"
    assert result["reason"] == "no_manual_events"
