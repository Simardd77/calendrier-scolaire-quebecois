"""Tests de la classification et de l'extraction d'evenements (parsers/events.py)."""

from __future__ import annotations

from datetime import date

import pytest

from custom_components.calendrier_scolaire_quebecois.models import EventCategory
from custom_components.calendrier_scolaire_quebecois.parsers.events import (
    classify,
    detect_school_year,
    extract_events_from_text,
)

# --- classify ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("libelle", "attendu"),
    [
        ("Journée pédagogique", EventCategory.PEDAGOGICAL_DAY),
        ("Journée pédago", EventCategory.PEDAGOGICAL_DAY),
        ("Congé férié", EventCategory.HOLIDAY),
        ("Semaine de relâche", EventCategory.HOLIDAY),
        ("Vacances des fêtes", EventCategory.HOLIDAY),
        ("Rentrée scolaire des élèves", EventCategory.TERM_START),
        ("Fin des classes", EventCategory.TERM_END),
        ("Examen de mathématiques", EventCategory.EXAM),
        ("Rencontre de parents", EventCategory.MEETING),
        ("Remise des bulletins", EventCategory.MEETING),
        ("Soirée seulement", EventCategory.MEETING),
        ("Présentation des enseignants", EventCategory.MEETING),
        ("Photo scolaire", EventCategory.EVENT),
    ],
)
def test_classify_par_mot_cle(libelle, attendu):
    """Chaque categorie est reconnue par ses mots-cles."""
    assert classify(libelle) == attendu


def test_classify_sans_mot_cle():
    """Un libelle sans mot-cle connu n'est pas classe."""
    assert classify("Zzz truc machin") is None


def test_classify_pedagogique_prime_sur_conge():
    """Une journee pedagogique est plus precise qu'un simple conge."""
    libelle = "Journée pédagogique (congé pour les élèves)"

    assert classify(libelle) == EventCategory.PEDAGOGICAL_DAY


def test_classify_rencontre_prime_sur_legende_pedagogique_fusionnee():
    """Une cellule de tableau peut fusionner une rencontre et une legende."""
    libelle = (
        "Basketball : Camp de sélection 9 septembre | "
        "Assemblée générale de parents Journée pédagogique | DGA"
    )

    assert classify(libelle) == EventCategory.MEETING


def test_classify_insensible_aux_accents():
    """Le texte extrait d'un PDF perd parfois ses accents."""
    assert classify("JOURNEE PEDAGOGIQUE") == EventCategory.PEDAGOGICAL_DAY
    assert classify("conge ferie") == EventCategory.HOLIDAY


def test_classify_rentree_du_personnel_n_est_pas_une_rentree():
    """Du point de vue d'une famille, seule la rentree des eleves borne l'annee."""
    assert classify("Rentrée des enseignants") == EventCategory.EVENT
    assert classify("Accueil du personnel") == EventCategory.EVENT


def test_classify_rentree_mentionnant_les_deux_publics():
    """Si les eleves sont mentionnes, la borne d'annee scolaire est conservee."""
    resultat = classify("Rentrée des enseignants et des élèves")

    assert resultat == EventCategory.TERM_START


def test_classify_travail_des_enseignants_est_une_pedagogique():
    """La formulation decrit une journee pedagogique sans la nommer."""
    resultat = classify("Journée de travail pour les enseignants")

    assert resultat == EventCategory.PEDAGOGICAL_DAY


# --- detect_school_year ------------------------------------------------------


def test_detect_school_year():
    """L'annee scolaire annoncee est plus fiable que la date du jour."""
    assert detect_school_year("Calendrier scolaire 2024-2025") == 2024
    assert detect_school_year("Année 2025 – 2026, approuvée") == 2025


def test_detect_school_year_annees_non_consecutives():
    """Deux annees qui ne se suivent pas ne designent pas une annee scolaire."""
    assert detect_school_year("Plan triennal 2024-2027") is None


def test_detect_school_year_absente():
    """Sans mention, l'annee scolaire reste indeterminee."""
    assert detect_school_year("Document sans millésime") is None


# --- extract_events_from_text ------------------------------------------------


def test_extraction_multi_lignes():
    """Chaque ligne datee produit un evenement classe."""
    texte = (
        "Rentrée scolaire des élèves: 3 septembre 2024\n"
        "Relâche: du 3 au 7 mars 2025\n"
        "Journée pédagogique le 4 octobre 2024\n"
    )

    evenements = extract_events_from_text(texte, "École Test", 2024)

    assert len(evenements) == 3
    assert [evenement.first_day for evenement in evenements] == [
        date(2024, 9, 3),
        date(2024, 10, 4),
        date(2025, 3, 3),
    ]
    assert [evenement.category for evenement in evenements] == [
        EventCategory.TERM_START,
        EventCategory.PEDAGOGICAL_DAY,
        EventCategory.HOLIDAY,
    ]


def test_extraction_conserve_la_source():
    """Le nom de la source est reporte sur chaque evenement."""
    evenements = extract_events_from_text(
        "Congé le 2 septembre 2024", "École Saint-Jean", 2024
    )

    assert len(evenements) == 1
    assert evenements[0].source == "École Saint-Jean"


def test_extraction_derive_le_titre_de_la_ligne():
    """Le titre est le reste de la ligne, sans la date ni les mots de liaison."""
    evenements = extract_events_from_text(
        "Journée pédagogique le 4 octobre 2024", "Test", 2024
    )

    assert len(evenements) == 1
    assert evenements[0].summary == "Journée pédagogique"


def test_extraction_titre_de_repli_par_categorie():
    """Une ligne reduite a une date recoit un libelle derive de sa categorie."""
    evenements = extract_events_from_text("Relâche 3 au 7 mars 2025", "Test", 2024)

    assert len(evenements) == 1
    assert evenements[0].summary == "Relâche"
    assert evenements[0].category == EventCategory.HOLIDAY


def test_extraction_plage_couvre_toute_la_periode():
    """Une plage donne un evenement unique couvrant toutes les journees."""
    evenements = extract_events_from_text(
        "Vacances des fêtes: du 23 décembre 2024 au 6 janvier 2025", "Test", 2024
    )

    assert len(evenements) == 1
    evenement = evenements[0]
    assert evenement.first_day == date(2024, 12, 23)
    assert evenement.last_day == date(2025, 1, 6)
    assert evenement.closes_school


def test_extraction_ignore_les_lignes_sans_date():
    """Une ligne sans date ne produit rien, meme avec un mot-cle."""
    texte = "Congé pédagogique à confirmer\nCongé le 2 septembre 2024\n"

    evenements = extract_events_from_text(texte, "Test", 2024)

    assert len(evenements) == 1
    assert evenements[0].first_day == date(2024, 9, 2)


def test_extraction_texte_vide():
    """Un document vide ne produit aucun evenement."""
    assert extract_events_from_text("", "Test", 2024) == []


def test_mode_strict_exclut_les_lignes_non_classees():
    """Le mode strict reduit le bruit au prix de quelques oublis."""
    texte = "Zzz truc machin le 15 novembre 2024"

    souple = extract_events_from_text(texte, "Test", 2024)
    strict = extract_events_from_text(texte, "Test", 2024, strict=True)

    assert len(souple) == 1
    assert souple[0].category == EventCategory.EVENT
    assert strict == []


def test_mode_strict_conserve_les_lignes_classees():
    """Une ligne reconnue par un mot-cle passe le mode strict."""
    texte = "Congé férié le 2 septembre 2024"

    strict = extract_events_from_text(texte, "Test", 2024, strict=True)

    assert len(strict) == 1
    assert strict[0].category == EventCategory.HOLIDAY


def test_extraction_dedoublonne_les_repetitions():
    """Un conge repete a l'identique dans le document n'est compte qu'une fois."""
    texte = "Congé le 2 septembre 2024\nCongé le 2 septembre 2024\n"

    evenements = extract_events_from_text(texte, "Test", 2024)

    assert len(evenements) == 1
