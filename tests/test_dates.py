"""Tests de l'extraction de dates (parsers/dates.py)."""

from __future__ import annotations

from datetime import date

from custom_components.calendrier_scolaire_quebecois.parsers.dates import (
    MAX_SPAN_DAYS,
    find_date_spans,
    normalize_two_digit_year,
    resolve_year,
    school_year_start_for,
    strip_date_text,
)


def test_school_year_start_for_apres_aout():
    """A partir d'aout, l'annee scolaire commence l'annee civile courante."""
    assert school_year_start_for(date(2024, 8, 1)) == 2024
    assert school_year_start_for(date(2024, 12, 31)) == 2024


def test_school_year_start_for_avant_aout():
    """Avant aout, l'annee scolaire a commence l'annee civile precedente."""
    assert school_year_start_for(date(2025, 3, 1)) == 2024
    assert school_year_start_for(date(2025, 7, 31)) == 2024


def test_resolve_year_deduit_l_annee_implicite():
    """Les mois d'aout a decembre appartiennent a l'annee d'ouverture."""
    assert resolve_year(9, 2024) == 2024
    assert resolve_year(12, 2024) == 2024
    assert resolve_year(1, 2024) == 2025
    assert resolve_year(6, 2024) == 2025


def test_normalize_two_digit_year():
    """Les annees sur deux chiffres basculent au seuil de 70."""
    assert normalize_two_digit_year(24) == 2024
    assert normalize_two_digit_year(69) == 2069
    assert normalize_two_digit_year(70) == 1970
    assert normalize_two_digit_year(2024) == 2024


def test_plage_sur_deux_mois_traverse_le_nouvel_an():
    """Une plage decembre-janvier incremente l'annee de la borne de fin."""
    spans = find_date_spans("du 23 décembre 2024 au 6 janvier 2025", 2024)

    assert len(spans) == 1
    span = spans[0]
    assert span.start == date(2024, 12, 23)
    assert span.last_day == date(2025, 1, 6)
    assert span.end_exclusive == date(2025, 1, 7)
    assert not span.is_single_day


def test_plage_sur_deux_mois_sans_annee_explicite():
    """L'annee absente est deduite de l'annee scolaire de reference."""
    spans = find_date_spans("du 23 décembre au 6 janvier", 2024)

    assert len(spans) == 1
    assert spans[0].start == date(2024, 12, 23)
    assert spans[0].last_day == date(2025, 1, 6)


def test_plage_dans_un_seul_mois():
    """La semaine de relache s'ecrit avec un seul nom de mois."""
    spans = find_date_spans("Relâche: du 3 au 7 mars 2025", 2024)

    assert len(spans) == 1
    assert spans[0].start == date(2025, 3, 3)
    assert spans[0].last_day == date(2025, 3, 7)


def test_plage_numerique():
    """Le format jour/mois/annee est reconnu de part et d'autre du separateur."""
    spans = find_date_spans("23/12/2024 au 06/01/2025", 2024)

    assert len(spans) == 1
    assert spans[0].start == date(2024, 12, 23)
    assert spans[0].last_day == date(2025, 1, 6)


def test_date_litterale_simple():
    """Une date unique produit une plage d'une seule journee."""
    spans = find_date_spans("Rentrée le 3 septembre 2024", 2024)

    assert len(spans) == 1
    assert spans[0].start == date(2024, 9, 3)
    assert spans[0].is_single_day
    assert spans[0].end_exclusive == date(2024, 9, 4)


def test_date_iso():
    """Le format ISO est reconnu sans etre confondu avec jour/mois/annee."""
    spans = find_date_spans("2024-09-03", 2024)

    assert len(spans) == 1
    assert spans[0].start == date(2024, 9, 3)


def test_suffixe_ordinal():
    """Le "1er" du mois est accepte."""
    spans = find_date_spans("Congé le 1er juillet 2025", 2024)

    assert len(spans) == 1
    assert spans[0].start == date(2025, 7, 1)


def test_nom_de_mois_dans_un_mot_ignore():
    """ "mai" a l'interieur de "maisons" ne doit pas produire de date."""
    assert find_date_spans("3 maisons ont été visitées", 2024) == []


def test_annee_seule_ne_produit_pas_de_date():
    """Un millesime isole n'est pas une date exploitable."""
    assert find_date_spans("Calendrier 2024-2025 approuvé", 2024) == []


def test_texte_sans_date():
    """Une ligne sans date ne produit aucune plage."""
    assert find_date_spans("Aucune information de date ici", 2024) == []
    assert find_date_spans("", 2024) == []


def test_plage_trop_longue_retombe_sur_des_dates_simples():
    """Au-dela de MAX_SPAN_DAYS, les bornes sont traitees separement."""
    texte = "du 3 septembre 2024 au 6 janvier 2026"
    span_jours = (date(2026, 1, 6) - date(2024, 9, 3)).days
    assert span_jours > MAX_SPAN_DAYS

    spans = find_date_spans(texte, 2024)

    assert len(spans) == 2
    assert all(span.is_single_day for span in spans)
    assert spans[0].start == date(2024, 9, 3)
    assert spans[1].start == date(2026, 1, 6)


def test_dates_triees_par_position():
    """Les plages sont rendues dans l'ordre d'apparition dans le texte."""
    spans = find_date_spans("Photo le 5 novembre 2024, examen le 3 février 2025", 2024)

    assert len(spans) == 2
    assert spans[0].match_start < spans[1].match_start
    assert spans[0].start == date(2024, 11, 5)
    assert spans[1].start == date(2025, 2, 3)


def test_strip_date_text_retire_l_expression_de_date():
    """Le libelle restant sert a deriver un titre lisible."""
    texte = "Congé pédagogique le 3 septembre 2024"
    spans = find_date_spans(texte, 2024)

    reste = strip_date_text(texte, spans)

    assert "Congé pédagogique" in reste
    assert "septembre" not in reste
    assert "2024" not in reste


def test_strip_date_text_sans_date_est_neutre():
    """Sans plage detectee, le texte est rendu tel quel."""
    assert strip_date_text("Texte inchangé", []) == "Texte inchangé"
