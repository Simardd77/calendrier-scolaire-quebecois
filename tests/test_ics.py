"""Tests de la serialisation iCalendar (ics.py)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from custom_components.calendrier_scolaire_quebecois.ics import (
    MAX_LINE_OCTETS,
    build_ics,
    escape_text,
    fold_line,
)
from custom_components.calendrier_scolaire_quebecois.models import (
    EventCategory,
    SchoolEvent,
)

NOW = datetime(2024, 9, 1, 12, 0, tzinfo=timezone.utc)


def _conge(summary="Congé", jour=date(2024, 12, 23), jours=1) -> SchoolEvent:
    """Construit un conge de journee entiere."""
    return SchoolEvent(
        summary=summary,
        start=jour,
        end=jour + timedelta(days=jours),
        category=EventCategory.HOLIDAY,
    )


def _lignes(flux: str) -> list[str]:
    """Decoupe un flux en lignes, sans deplier."""
    return flux.split("\r\n")


# --- escape_text -------------------------------------------------------------


def test_escape_text_virgule_et_point_virgule():
    """Une virgule non echappee couperait la propriete en deux."""
    assert escape_text("Photo scolaire, maternelle") == "Photo scolaire\\, maternelle"
    assert escape_text("a;b") == "a\\;b"


def test_escape_text_barre_oblique_traitee_en_premier():
    """La barre oblique inverse ne doit pas echapper les echappements ajoutes."""
    assert escape_text("a\\b,c") == "a\\\\b\\,c"


def test_escape_text_retours_a_la_ligne():
    """Les retours a la ligne deviennent la sequence \\n."""
    assert escape_text("ligne1\nligne2") == "ligne1\\nligne2"
    assert escape_text("ligne1\r\nligne2") == "ligne1\\nligne2"


def test_escape_text_ne_touche_pas_au_deux_points():
    """Le deux-points est autorise dans une valeur."""
    assert escape_text("Congé : hiver") == "Congé : hiver"


# --- fold_line ---------------------------------------------------------------


def test_fold_line_ligne_courte_inchangee():
    """Une ligne sous la limite n'est pas pliee."""
    assert fold_line("SUMMARY:Congé") == ["SUMMARY:Congé"]


def test_fold_line_respecte_la_limite_en_octets():
    """Chaque ligne produite tient dans la limite, accents compris."""
    ligne = "SUMMARY:" + "é" * 200

    parties = fold_line(ligne)

    assert len(parties) > 1
    assert all(len(p.encode("utf-8")) <= MAX_LINE_OCTETS for p in parties)


def test_fold_line_continuations_prefixees_par_une_espace():
    """Le depliage se fait sur l'espace initial des lignes de continuation."""
    parties = fold_line("DESCRIPTION:" + "a" * 200)

    assert not parties[0].startswith(" ")
    assert all(p.startswith(" ") for p in parties[1:])


def test_fold_line_est_reversible():
    """Le depliage restitue exactement la ligne d'origine."""
    ligne = "SUMMARY:" + "Journée pédagogique très détaillée " * 8

    parties = fold_line(ligne)
    deplie = parties[0] + "".join(p[1:] for p in parties[1:])

    assert deplie == ligne


def test_fold_line_ne_scinde_pas_un_caractere_multioctet():
    """Chaque ligne reste decodable en UTF-8."""
    parties = fold_line("SUMMARY:" + "é" * 100)

    for partie in parties:
        partie.encode("utf-8").decode("utf-8")


# --- build_ics: structure ----------------------------------------------------


def test_build_ics_enveloppe():
    """Le flux porte les proprietes attendues d'un calendrier publie."""
    flux = build_ics("Calendrier scolaire", [_conge()], now=NOW)
    lignes = _lignes(flux)

    assert lignes[0] == "BEGIN:VCALENDAR"
    assert "VERSION:2.0" in lignes
    assert "CALSCALE:GREGORIAN" in lignes
    assert "METHOD:PUBLISH" in lignes
    assert "X-WR-CALNAME:Calendrier scolaire" in lignes
    assert lignes[-2] == "END:VCALENDAR"


def test_build_ics_termine_par_crlf():
    """RFC 5545 impose CRLF, y compris en fin de flux."""
    flux = build_ics("Test", [_conge()], now=NOW)

    assert flux.endswith("\r\n")
    assert "\n" not in flux.replace("\r\n", "")


def test_build_ics_calendrier_vide_reste_valide():
    """Un calendrier sans evenement doit produire un flux exploitable."""
    flux = build_ics("Test", [], now=NOW)
    lignes = _lignes(flux)

    assert lignes[0] == "BEGIN:VCALENDAR"
    assert "BEGIN:VEVENT" not in lignes
    assert lignes[-2] == "END:VCALENDAR"


# --- build_ics: journees entieres -------------------------------------------


def test_journee_entiere_utilise_value_date():
    """C'est ce parametre qui evite l'affichage sur une plage horaire."""
    flux = build_ics("Test", [_conge()], now=NOW)
    lignes = _lignes(flux)

    assert "DTSTART;VALUE=DATE:20241223" in lignes
    assert "DTEND;VALUE=DATE:20241224" in lignes


def test_journee_entiere_sans_horodatage():
    """Aucune heure ne doit apparaitre dans les bornes d'une journee entiere."""
    flux = build_ics("Test", [_conge()], now=NOW)

    for ligne in _lignes(flux):
        if ligne.startswith(("DTSTART", "DTEND")):
            assert "T" not in ligne.split(":", 1)[1]


def test_plage_de_plusieurs_jours_conserve_la_fin_exclusive():
    """Le conge des fetes doit couvrir toute sa duree."""
    conge = _conge(jour=date(2024, 12, 23), jours=15)

    lignes = _lignes(build_ics("Test", [conge], now=NOW))

    assert "DTSTART;VALUE=DATE:20241223" in lignes
    assert "DTEND;VALUE=DATE:20250107" in lignes


def test_journee_entiere_est_transparente():
    """Un conge informe sans marquer l'utilisateur comme occupe."""
    assert "TRANSP:TRANSPARENT" in _lignes(build_ics("Test", [_conge()], now=NOW))


# --- build_ics: evenements horodates ----------------------------------------


def test_evenement_horodate_converti_en_utc():
    """Un evenement avec heure est publie en UTC."""
    debut = datetime(2024, 10, 4, 18, 30, tzinfo=timezone(timedelta(hours=-4)))
    evenement = SchoolEvent(
        summary="Rencontre de parents",
        start=debut,
        end=debut + timedelta(hours=2),
        category=EventCategory.MEETING,
    )

    lignes = _lignes(build_ics("Test", [evenement], now=NOW))

    assert "DTSTART:20241004T223000Z" in lignes
    assert "DTEND:20241005T003000Z" in lignes
    assert "TRANSP:TRANSPARENT" not in lignes


# --- build_ics: contenu des evenements --------------------------------------


def test_evenement_porte_un_uid_stable_et_un_dtstamp():
    """Un UID stable evite les doublons a chaque rafraichissement."""
    conge = _conge()

    premier = _lignes(build_ics("Test", [conge], now=NOW))
    second = _lignes(build_ics("Test", [conge], now=NOW))

    uids = [ligne for ligne in premier if ligne.startswith("UID:")]
    assert len(uids) == 1
    assert uids[0].endswith("@calendrier-scolaire-quebecois")
    assert uids == [ligne for ligne in second if ligne.startswith("UID:")]
    assert "DTSTAMP:20240901T120000Z" in premier


def test_titre_est_echappe():
    """Un titre contenant une virgule ne doit pas corrompre l'evenement."""
    conge = _conge(summary="Photo scolaire, maternelle")

    assert "SUMMARY:Photo scolaire\\, maternelle" in _lignes(
        build_ics("Test", [conge], now=NOW)
    )


def test_categorie_publiee():
    """La categorie permet un filtrage cote client."""
    assert "CATEGORIES:holiday" in _lignes(build_ics("Test", [_conge()], now=NOW))


def test_description_et_lieu_omis_si_vides():
    """Les proprietes optionnelles vides ne sont pas emises."""
    lignes = _lignes(build_ics("Test", [_conge()], now=NOW))

    assert not any(ligne.startswith("DESCRIPTION:") for ligne in lignes)
    assert not any(ligne.startswith("LOCATION:") for ligne in lignes)


def test_description_et_lieu_emis_si_presents():
    """Les proprietes optionnelles renseignees sont publiees et echappees."""
    evenement = SchoolEvent(
        summary="Sortie",
        start=date(2024, 10, 4),
        end=date(2024, 10, 5),
        category=EventCategory.EVENT,
        description="Apporter un lunch, une bouteille d'eau",
        location="Musée",
    )

    lignes = _lignes(build_ics("Test", [evenement], now=NOW))

    assert "DESCRIPTION:Apporter un lunch\\, une bouteille d'eau" in lignes
    assert "LOCATION:Musée" in lignes


@pytest.mark.parametrize("nombre", [1, 5, 40])
def test_un_bloc_vevent_par_evenement(nombre):
    """Chaque evenement produit exactement une composante VEVENT."""
    evenements = [
        _conge(summary=f"Congé {index}", jour=date(2024, 9, 2) + timedelta(days=index))
        for index in range(nombre)
    ]

    lignes = _lignes(build_ics("Test", evenements, now=NOW))

    assert lignes.count("BEGIN:VEVENT") == nombre
    assert lignes.count("END:VEVENT") == nombre
