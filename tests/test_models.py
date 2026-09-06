"""Tests des modeles de donnees (models.py)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from custom_components.calendrier_scolaire_quebecois.models import (
    MAX_SUMMARY_LENGTH,
    CalendarSource,
    EventCategory,
    SchoolEvent,
    build_source_id,
    clean_summary,
    deduplicate_events,
    exclude_weekends,
    is_calendar_like,
    is_weekend,
    merge_extraction_results,
    normalize_text,
    resolve_current_term,
    resolve_term_membership,
    singularize_one_day_summaries,
    split_on_weekends,
)


def _jour(annee: int, mois: int, jour: int) -> SchoolEvent:
    """Construit un evenement d'une journee, pour alleger les tests."""
    debut = date(annee, mois, jour)
    return SchoolEvent(
        summary="Test",
        start=debut,
        end=debut + timedelta(days=1),
    )


# --- normalize_text / clean_summary -----------------------------------------


def test_normalize_text_retire_accents_et_casse():
    """La normalisation permet de comparer des libelles ecrits differemment."""
    assert normalize_text("Congé Pédagogique") == "conge pedagogique"
    assert normalize_text("RELÂCHE") == "relache"
    assert normalize_text("Été") == "ete"


def test_clean_summary_reduit_les_espaces_et_la_ponctuation():
    """Un titre extrait d'un PDF arrive avec des espaces et de la ponctuation."""
    assert clean_summary("  Journée   pédagogique  - ") == "Journée pédagogique"
    assert clean_summary("Congé :") == "Congé"


def test_clean_summary_conserve_les_parentheses():
    """Un libelle entre parentheses doit rester equilibre."""
    valeur = "Journées pédagogiques (congé pour les élèves)"
    assert clean_summary(valeur) == valeur


def test_clean_summary_tronque_sur_une_frontiere_de_mot():
    """Un titre trop long est tronque sans couper un mot en deux."""
    resultat = clean_summary("mot " * 100)

    assert resultat.endswith("...")
    assert len(resultat) <= MAX_SUMMARY_LENGTH + 3


# --- CalendarSource ----------------------------------------------------------


def test_build_source_id_est_deterministe():
    """Le meme URL donne toujours le meme identifiant."""
    premier = build_source_id("https://example.com/calendrier.pdf")
    second = build_source_id("https://example.com/calendrier.pdf")

    assert premier == second
    assert len(premier) == 12
    assert premier != build_source_id("https://example.com/autre.pdf")


def test_calendar_source_aller_retour_dictionnaire():
    """La source survit a la serialisation dans l'entree de configuration."""
    source = CalendarSource(
        source_id="abc123",
        name="Mon école",
        url="https://example.com/calendrier.pdf",
        source_type="direct_url",
    )

    reconstruite = CalendarSource.from_dict(source.as_dict())

    assert reconstruite == source


def test_calendar_source_genere_un_id_absent():
    """Sans identifiant fourni, il est derive de l'URL."""
    source = CalendarSource.from_dict({"url": "https://example.com/c.pdf"})

    assert source.source_id == build_source_id("https://example.com/c.pdf")
    assert source.source_type == "direct_url"


def test_calendar_source_exige_une_url():
    """Une source sans URL n'est pas exploitable."""
    with pytest.raises(ValueError):
        CalendarSource.from_dict({"name": "Sans URL"})

    with pytest.raises(ValueError):
        CalendarSource.from_dict({"url": "   "})


# --- SchoolEvent -------------------------------------------------------------


def test_school_event_journee_entiere():
    """Pour une journee entiere, la fin est exclusive."""
    evenement = SchoolEvent(
        summary="Congé",
        start=date(2024, 12, 23),
        end=date(2024, 12, 24),
        category=EventCategory.HOLIDAY,
    )

    assert evenement.all_day
    assert evenement.first_day == date(2024, 12, 23)
    assert evenement.last_day == date(2024, 12, 23)


def test_school_event_horodate():
    """Un evenement horodate n'est pas une journee entiere."""
    debut = datetime(2024, 9, 3, 8, 0, tzinfo=timezone.utc)
    evenement = SchoolEvent(
        summary="Rencontre",
        start=debut,
        end=debut + timedelta(hours=2),
        category=EventCategory.MEETING,
    )

    assert not evenement.all_day
    assert evenement.first_day == date(2024, 9, 3)


def test_school_event_refuse_bornes_mixtes():
    """Melanger date et datetime est une erreur de programmation."""
    with pytest.raises(ValueError):
        SchoolEvent(
            summary="Incohérent",
            start=date(2024, 9, 3),
            end=datetime(2024, 9, 4, tzinfo=timezone.utc),
        )


def test_school_event_refuse_une_fin_anterieure():
    """La fin doit etre strictement posterieure au debut."""
    with pytest.raises(ValueError):
        SchoolEvent(
            summary="Vide",
            start=date(2024, 9, 3),
            end=date(2024, 9, 3),
        )


def test_school_event_occurs_on():
    """La couverture inclut la premiere et la derniere journee."""
    evenement = SchoolEvent(
        summary="Relâche",
        start=date(2025, 3, 3),
        end=date(2025, 3, 8),
        category=EventCategory.HOLIDAY,
    )

    assert evenement.occurs_on(date(2025, 3, 3))
    assert evenement.occurs_on(date(2025, 3, 7))
    assert not evenement.occurs_on(date(2025, 3, 8))
    assert not evenement.occurs_on(date(2025, 3, 2))


@pytest.mark.parametrize(
    ("categorie", "ferme"),
    [
        (EventCategory.HOLIDAY, True),
        (EventCategory.PEDAGOGICAL_DAY, True),
        (EventCategory.TERM_START, False),
        (EventCategory.TERM_END, False),
        (EventCategory.EXAM, False),
        (EventCategory.MEETING, False),
        (EventCategory.EVENT, False),
    ],
)
def test_closes_school_par_categorie(categorie, ferme):
    """La rentree et la fin des classes sont des journees de classe."""
    evenement = SchoolEvent(
        summary="Test",
        start=date(2024, 9, 3),
        end=date(2024, 9, 4),
        category=categorie,
    )

    assert evenement.closes_school is ferme


def test_is_holiday_distingue_le_conge_de_la_pedagogique():
    """Une journee pedagogique ferme l'ecole sans etre des vacances."""
    pedagogique = SchoolEvent(
        summary="Journée pédagogique",
        start=date(2024, 10, 4),
        end=date(2024, 10, 5),
        category=EventCategory.PEDAGOGICAL_DAY,
    )

    assert pedagogique.closes_school
    assert not pedagogique.is_holiday


def test_uid_est_deterministe():
    """L'identifiant d'un evenement est stable entre deux analyses."""
    premier = _jour(2024, 9, 3)
    second = _jour(2024, 9, 3)

    assert premier.uid == second.uid
    assert premier.uid != _jour(2024, 9, 4).uid


# --- deduplicate_events -----------------------------------------------------


def test_deduplicate_events_ignore_casse_et_accents():
    """Deux sources ecrivant le meme conge differemment ne le doublent pas."""
    evenements = [
        SchoolEvent(
            summary="Congé férié",
            start=date(2024, 9, 2),
            end=date(2024, 9, 3),
            category=EventCategory.HOLIDAY,
            source="A",
        ),
        SchoolEvent(
            summary="CONGE FERIE",
            start=date(2024, 9, 2),
            end=date(2024, 9, 3),
            category=EventCategory.HOLIDAY,
            source="B",
        ),
    ]

    assert len(deduplicate_events(evenements)) == 1


def test_deduplicate_events_conserve_les_recurrences():
    """Un meme libelle a des dates differentes reste deux evenements."""
    evenements = [
        SchoolEvent(
            summary="Journée pédagogique",
            start=date(2024, 10, 4),
            end=date(2024, 10, 5),
            category=EventCategory.PEDAGOGICAL_DAY,
        ),
        SchoolEvent(
            summary="Journée pédagogique",
            start=date(2024, 11, 15),
            end=date(2024, 11, 16),
            category=EventCategory.PEDAGOGICAL_DAY,
        ),
    ]

    assert len(deduplicate_events(evenements)) == 2


def test_deduplicate_events_trie_chronologiquement():
    """La sortie est triee, quel que soit l'ordre d'entree."""
    resultat = deduplicate_events([_jour(2025, 3, 3), _jour(2024, 9, 3)])

    assert [evenement.first_day for evenement in resultat] == [
        date(2024, 9, 3),
        date(2025, 3, 3),
    ]


def test_deduplicate_events_liste_vide():
    """Aucun evenement en entree donne aucun evenement en sortie."""
    assert deduplicate_events([]) == []


# --- merge_extraction_results -----------------------------------------------


def test_merge_privilegie_la_grille_et_retire_le_bruit_textuel():
    """Quand la grille a parle, le texte non type est du bruit."""
    bruit = SchoolEvent(
        summary="Note en prose",
        start=date(2024, 9, 10),
        end=date(2024, 9, 11),
        category=EventCategory.EVENT,
    )
    rentree = SchoolEvent(
        summary="Rentrée scolaire",
        start=date(2024, 9, 3),
        end=date(2024, 9, 4),
        category=EventCategory.TERM_START,
    )
    grille = SchoolEvent(
        summary="Journée pédagogique",
        start=date(2024, 10, 4),
        end=date(2024, 10, 5),
        category=EventCategory.PEDAGOGICAL_DAY,
    )

    resultat = merge_extraction_results([bruit, rentree], [grille])

    resumes = [evenement.summary for evenement in resultat]
    assert "Note en prose" not in resumes
    assert "Rentrée scolaire" in resumes
    assert "Journée pédagogique" in resumes


def test_merge_conserve_tout_le_texte_sans_grille():
    """Sans resultat geometrique, le document est un calendrier redige."""
    bruit = SchoolEvent(
        summary="Note en prose",
        start=date(2024, 9, 10),
        end=date(2024, 9, 11),
        category=EventCategory.EVENT,
    )

    resultat = merge_extraction_results([bruit], [])

    assert [evenement.summary for evenement in resultat] == ["Note en prose"]


# --- resolve_term_membership ------------------------------------------------


def test_term_membership_indetermine_sans_borne():
    """Sans rentree ni fin annoncee, la question ne peut pas etre tranchee."""
    assert resolve_term_membership(date(2024, 10, 1), [], []) is None


def test_term_membership_pendant_l_annee():
    """Entre la rentree et la fin des classes, l'ecole est en periode."""
    resultat = resolve_term_membership(
        date(2024, 10, 1), [date(2024, 9, 3)], [date(2025, 6, 20)]
    )

    assert resultat is True


def test_term_membership_apres_la_fin_des_classes():
    """Passe la derniere journee annoncee, on est hors periode."""
    resultat = resolve_term_membership(
        date(2025, 8, 1), [date(2024, 9, 3)], [date(2025, 6, 20)]
    )

    assert resultat is False


def test_term_membership_avant_la_premiere_rentree():
    """Avant la rentree annoncee, on est hors periode."""
    resultat = resolve_term_membership(date(2024, 8, 1), [date(2024, 9, 3)], [])

    assert resultat is False


def test_term_membership_fin_implicite_a_la_fin_juin():
    """Sans fin annoncee, la periode est bornee a la fin juin suivante."""
    assert resolve_term_membership(date(2025, 1, 15), [date(2024, 9, 3)], []) is True
    assert resolve_term_membership(date(2025, 8, 15), [date(2024, 9, 3)], []) is False


def test_term_membership_avec_une_fin_seulement():
    """Une fin annoncee sans rentree implique une periode courante."""
    assert resolve_term_membership(date(2025, 1, 1), [], [date(2025, 6, 20)]) is True


def test_term_membership_ete_entre_deux_calendriers():
    """L'ete separant deux annees chainees est hors periode.

    Un calendrier couvre de juillet a juin: celui de 2026-2027 place juillet et
    aout 2026 avant sa rentree. Ces deux mois prolongent l'annee precedente et
    ne doivent pas etre declares ouverts sous pretexte qu'une rentree les
    precede et qu'une fin les suit.
    """
    starts = [date(2025, 9, 2), date(2026, 9, 1)]
    ends = [date(2026, 6, 23), date(2027, 6, 23)]

    assert resolve_term_membership(date(2025, 10, 1), starts, ends) is True
    assert resolve_term_membership(date(2026, 6, 23), starts, ends) is True
    assert resolve_term_membership(date(2026, 6, 24), starts, ends) is False
    assert resolve_term_membership(date(2026, 7, 15), starts, ends) is False
    assert resolve_term_membership(date(2026, 8, 31), starts, ends) is False
    assert resolve_term_membership(date(2026, 9, 1), starts, ends) is True
    assert resolve_term_membership(date(2027, 3, 1), starts, ends) is True
    assert resolve_term_membership(date(2027, 7, 15), starts, ends) is False


def test_term_membership_trois_calendriers_consecutifs():
    """Le chainage tient au-dela de deux annees."""
    starts = [date(2025, 9, 2), date(2026, 9, 1), date(2027, 8, 30)]
    ends = [date(2026, 6, 23), date(2027, 6, 23), date(2028, 6, 21)]

    assert resolve_term_membership(date(2026, 7, 15), starts, ends) is False
    assert resolve_term_membership(date(2027, 7, 15), starts, ends) is False
    assert resolve_term_membership(date(2027, 8, 30), starts, ends) is True
    assert resolve_term_membership(date(2028, 1, 10), starts, ends) is True
    assert resolve_term_membership(date(2028, 7, 1), starts, ends) is False


# --- resolve_current_term ----------------------------------------------------


def test_current_term_sans_aucune_borne():
    """Sans rentree ni fin, il n'y a rien a rapporter."""
    assert resolve_current_term(date(2026, 10, 1), [], []) == (None, None)


def test_current_term_annee_unique():
    """Un seul calendrier: ses dates sont rapportees toute l'annee."""
    starts = [date(2026, 9, 1)]
    ends = [date(2027, 6, 23)]
    attendu = (date(2026, 9, 1), date(2027, 6, 23))

    assert resolve_current_term(date(2026, 12, 1), starts, ends) == attendu
    # Avant la rentree comme apres la fin, faute de mieux, la meme annee.
    assert resolve_current_term(date(2026, 7, 15), starts, ends) == attendu
    assert resolve_current_term(date(2027, 7, 15), starts, ends) == attendu


def test_current_term_ajouter_l_annee_prochaine_ne_change_rien():
    """Charger le calendrier suivant ne deplace pas l'annee en cours.

    C'est l'exigence principale: la fin annoncee doit rester celle de l'annee
    qui court, meme quand un document plus lointain est charge.
    """
    seul = ([date(2026, 9, 1)], [date(2027, 6, 23)])
    avec_suivant = (
        [date(2026, 9, 1), date(2027, 8, 30)],
        [date(2027, 6, 23), date(2028, 6, 21)],
    )
    jour = date(2026, 12, 1)

    assert resolve_current_term(jour, *seul) == resolve_current_term(
        jour, *avec_suivant
    )
    assert resolve_current_term(jour, *avec_suivant) == (
        date(2026, 9, 1),
        date(2027, 6, 23),
    )


def test_current_term_bascule_a_la_fin_de_l_annee():
    """Passe la fin des classes, l'annee suivante devient celle rapportee."""
    starts = [date(2026, 9, 1), date(2027, 8, 30)]
    ends = [date(2027, 6, 23), date(2028, 6, 21)]

    courante = (date(2026, 9, 1), date(2027, 6, 23))
    suivante = (date(2027, 8, 30), date(2028, 6, 21))

    assert resolve_current_term(date(2027, 6, 23), starts, ends) == courante
    assert resolve_current_term(date(2027, 6, 24), starts, ends) == suivante
    assert resolve_current_term(date(2027, 7, 15), starts, ends) == suivante
    assert resolve_current_term(date(2027, 11, 1), starts, ends) == suivante


def test_current_term_annee_passee_non_rapportee():
    """Avec deux annees ecoulees, c'est celle du jour qui est rapportee."""
    starts = [date(2025, 9, 2), date(2026, 9, 1)]
    ends = [date(2026, 6, 23), date(2027, 6, 23)]

    assert resolve_current_term(date(2025, 10, 1), starts, ends) == (
        date(2025, 9, 2),
        date(2026, 6, 23),
    )
    assert resolve_current_term(date(2026, 12, 1), starts, ends) == (
        date(2026, 9, 1),
        date(2027, 6, 23),
    )


def test_current_term_sans_fin_annoncee():
    """Une rentree sans fin rapporte None pour la fin."""
    assert resolve_current_term(date(2027, 1, 15), [date(2026, 9, 1)], []) == (
        date(2026, 9, 1),
        None,
    )


def test_current_term_sans_rentree_annoncee():
    """Une fin sans rentree rapporte None pour la rentree."""
    assert resolve_current_term(date(2027, 1, 1), [], [date(2027, 6, 23)]) == (
        None,
        date(2027, 6, 23),
    )


def test_current_term_coherent_avec_la_periode_scolaire():
    """Quand l'ecole est en periode, l'annee rapportee contient la journee."""
    starts = [date(2025, 9, 2), date(2026, 9, 1), date(2027, 8, 30)]
    ends = [date(2026, 6, 23), date(2027, 6, 23), date(2028, 6, 21)]

    jour = date(2025, 9, 2)
    while jour <= date(2028, 6, 21):
        if resolve_term_membership(jour, starts, ends) is True:
            debut, fin = resolve_current_term(jour, starts, ends)
            assert debut is not None and debut <= jour, jour
            assert fin is not None and jour <= fin, jour
        jour += timedelta(days=1)


# --- is_calendar_like -------------------------------------------------------


def test_is_calendar_like_refuse_une_liste_vide():
    """Un document sans evenement n'est pas un calendrier."""
    assert is_calendar_like([]) is False


def test_is_calendar_like_refuse_les_evenements_non_types():
    """Un reglement ou un rapport ne produit que des dates sans categorie."""
    evenements = [
        SchoolEvent(
            summary="Adopté par le conseil",
            start=date(2024, 9, 10),
            end=date(2024, 9, 11),
            category=EventCategory.EVENT,
        ),
        SchoolEvent(
            summary="Révision prévue",
            start=date(2025, 3, 1),
            end=date(2025, 3, 2),
            category=EventCategory.EVENT,
        ),
    ]

    assert is_calendar_like(evenements) is False


@pytest.mark.parametrize(
    "categorie",
    [
        EventCategory.HOLIDAY,
        EventCategory.PEDAGOGICAL_DAY,
        EventCategory.TERM_START,
        EventCategory.TERM_END,
        EventCategory.EXAM,
        EventCategory.MEETING,
    ],
)
def test_is_calendar_like_accepte_un_seul_evenement_type(categorie):
    """Un seul marqueur scolaire suffit a reconnaitre un calendrier."""
    evenements = [
        SchoolEvent(
            summary="Bruit",
            start=date(2024, 9, 10),
            end=date(2024, 9, 11),
            category=EventCategory.EVENT,
        ),
        SchoolEvent(
            summary="Marqueur scolaire",
            start=date(2024, 12, 23),
            end=date(2024, 12, 24),
            category=categorie,
        ),
    ]

    assert is_calendar_like(evenements) is True


# --- fins de semaine --------------------------------------------------------


def _fermeture(debut: date, jours: int, categorie=EventCategory.HOLIDAY):
    """Construit une fermeture d'ecole couvrant plusieurs journees."""
    return SchoolEvent(
        summary="Congé",
        start=debut,
        end=debut + timedelta(days=jours),
        category=categorie,
    )


def test_is_weekend():
    """Samedi et dimanche seulement."""
    assert is_weekend(date(2024, 12, 28)) is True
    assert is_weekend(date(2024, 12, 29)) is True
    assert is_weekend(date(2024, 12, 27)) is False
    assert is_weekend(date(2024, 12, 30)) is False


def test_split_conge_des_fetes_reel():
    """Le congé des fêtes 2024-2025 se découpe en trois semaines de classe."""
    # Le 23 décembre 2024 est un lundi, le 6 janvier 2025 un lundi.
    conge = _fermeture(date(2024, 12, 23), 15)

    segments = split_on_weekends(conge)

    bornes = [(segment.first_day, segment.last_day) for segment in segments]
    assert bornes == [
        (date(2024, 12, 23), date(2024, 12, 27)),
        (date(2024, 12, 30), date(2025, 1, 3)),
        (date(2025, 1, 6), date(2025, 1, 6)),
    ]


def test_split_conserve_la_categorie_et_le_titre():
    """Le découpage ne change que les bornes."""
    conge = _fermeture(date(2024, 12, 23), 15)

    for segment in split_on_weekends(conge):
        assert segment.summary == "Congé"
        assert segment.category is EventCategory.HOLIDAY
        assert segment.closes_school


def test_split_semaine_de_relache_intacte():
    """Une plage entièrement en semaine ressort inchangée."""
    # Le 3 mars 2025 est un lundi, le 7 un vendredi.
    relache = _fermeture(date(2025, 3, 3), 5)

    assert split_on_weekends(relache) == [relache]


def test_split_journee_unique_en_semaine_intacte():
    """Une journée pédagogique en semaine n'est pas touchée."""
    pedago = _fermeture(date(2024, 10, 4), 1, categorie=EventCategory.PEDAGOGICAL_DAY)

    assert split_on_weekends(pedago) == [pedago]


def test_split_fermeture_entierement_en_fin_de_semaine_disparait():
    """Une fermeture ne couvrant qu'un week-end ne décrit aucune journée de classe."""
    # Les 28 et 29 décembre 2024 sont un samedi et un dimanche.
    assert split_on_weekends(_fermeture(date(2024, 12, 28), 2)) == []


def test_split_retire_les_bornes_de_fin_de_semaine():
    """Un congé débutant un samedi commence en réalité le lundi."""
    # Du samedi 28 décembre au mercredi 1er janvier.
    segments = split_on_weekends(_fermeture(date(2024, 12, 28), 5))

    assert len(segments) == 1
    assert segments[0].first_day == date(2024, 12, 30)
    assert segments[0].last_day == date(2025, 1, 1)


def test_split_ne_touche_pas_aux_evenements_ordinaires():
    """Une activité annoncée un samedi est réelle et doit être conservée."""
    sortie = SchoolEvent(
        summary="Carnaval",
        start=date(2025, 2, 8),
        end=date(2025, 2, 10),
        category=EventCategory.EVENT,
    )

    assert split_on_weekends(sortie) == [sortie]


def test_split_ne_touche_pas_aux_evenements_horodates():
    """Une rencontre de parents garde ses bornes horaires."""
    debut = datetime(2024, 10, 4, 18, 0, tzinfo=timezone.utc)
    rencontre = SchoolEvent(
        summary="Rencontre",
        start=debut,
        end=debut + timedelta(hours=2),
        category=EventCategory.MEETING,
    )

    assert split_on_weekends(rencontre) == [rencontre]


def test_exclude_weekends_sur_un_lot():
    """Le lot est découpé, dédoublonné et trié."""
    evenements = [
        _fermeture(date(2024, 12, 23), 15),
        _fermeture(date(2025, 3, 3), 5),
    ]

    resultat = exclude_weekends(evenements)

    assert len(resultat) == 4
    assert [event.first_day for event in resultat] == [
        date(2024, 12, 23),
        date(2024, 12, 30),
        date(2025, 1, 6),
        date(2025, 3, 3),
    ]


def test_exclude_weekends_aucun_jour_de_classe_couvert():
    """Aucun samedi ni dimanche ne subsiste dans les fermetures."""
    resultat = exclude_weekends([_fermeture(date(2024, 12, 23), 15)])

    for event in resultat:
        jour = event.first_day
        while jour <= event.last_day:
            assert not is_weekend(jour), jour
            jour += timedelta(days=1)


# --- singularize_one_day_summaries -------------------------------------------


def _titre(summary: str, jours: int) -> SchoolEvent:
    """Construit un evenement portant un titre et couvrant N journees."""
    debut = date(2026, 9, 7)
    return SchoolEvent(
        summary=summary,
        start=debut,
        end=debut + timedelta(days=jours),
        category=EventCategory.HOLIDAY,
    )


def _accorde(summary: str, jours: int = 1) -> str:
    """Retourne le titre accorde pour un evenement de N journees."""
    return singularize_one_day_summaries([_titre(summary, jours)])[0].summary


def test_singularize_accorde_la_tete_seulement():
    """Le complement reste au pluriel: seul le substantif de tete s'accorde."""
    assert _accorde("Congés pour les élèves, les enseignantes et les enseignants") == (
        "Congé pour les élèves, les enseignantes et les enseignants"
    )


def test_singularize_accorde_l_adjectif_avec_le_nom():
    """Sans l'adjectif, on obtiendrait le bancal 'Journee pedagogiques'."""
    assert _accorde("Journées pédagogiques (congé pour les élèves)") == (
        "Journée pédagogique (congé pour les élèves)"
    )
    assert _accorde("Journées pédagogiques pour force majeure") == (
        "Journée pédagogique pour force majeure"
    )


def test_singularize_conserve_accents_et_casse_du_document():
    """Le singulier est derive du texte lu, non d'une orthographe codee ici."""
    assert _accorde("CONGÉS fériés") == "CONGÉ fériés"
    assert _accorde("congés du printemps") == "congé du printemps"


def test_singularize_n_accorde_qu_un_mot_quand_la_table_le_dit():
    """Les parents restent plusieurs dans une rencontre de parents."""
    assert _accorde("Rencontres de parents") == "Rencontre de parents"


def test_singularize_laisse_les_pluriels_invariables():
    """'Vacances' n'a pas de singulier: la tete est absente de la table."""
    assert _accorde("Vacances d'été") == "Vacances d'été"


def test_singularize_laisse_les_titres_deja_au_singulier():
    """Un libelle deja accorde traverse la fonction intact."""
    for titre in (
        "Rentrée scolaire des élèves",
        "Fin des classes pour les élèves",
        "Semaine de relâche",
        "Congé - jour férié",
        "Fermeture du Centre de services scolaire de Montréal",
    ):
        assert _accorde(titre) == titre


def test_singularize_exige_un_mot_entier():
    """'Congestion' ne commence pas par le mot 'conges'."""
    assert _accorde("Congestion du réseau") == "Congestion du réseau"
    assert _accorde("Congés-vacances") == "Congés-vacances"


def test_singularize_epargne_les_evenements_de_plusieurs_jours():
    """Le pluriel est juste des que l'evenement couvre plus d'une journee."""
    titre = "Congés pour les élèves, les enseignantes et les enseignants"
    assert _accorde(titre, jours=1) != titre
    assert _accorde(titre, jours=2) == titre
    assert _accorde(titre, jours=5) == titre


def test_singularize_preserve_les_autres_champs():
    """Seul le titre change: dates, categorie et source sont conserves."""
    debut = date(2026, 10, 12)
    source = SchoolEvent(
        summary="Congés fériés",
        start=debut,
        end=debut + timedelta(days=1),
        category=EventCategory.HOLIDAY,
        source="CSS des Patriotes",
        description="note",
    )

    resultat = singularize_one_day_summaries([source])[0]

    assert resultat.summary == "Congé fériés"
    assert resultat.start == source.start
    assert resultat.end == source.end
    assert resultat.category is source.category
    assert resultat.source == source.source
    assert resultat.description == source.description


def test_singularize_conserve_l_ordre_et_le_compte():
    """La fonction ne filtre ni ne reordonne les evenements."""
    entrees = [
        _titre("Congés fériés", 1),
        _titre("Journées pédagogiques", 3),
        _titre("Vacances", 1),
    ]

    resultat = singularize_one_day_summaries(entrees)

    assert len(resultat) == len(entrees)
    assert [e.summary for e in resultat] == [
        "Congé fériés",
        "Journées pédagogiques",
        "Vacances",
    ]


def test_singularize_apres_le_decoupage_des_fins_de_semaine():
    """L'accord tient compte des journees isolees produites par le decoupage.

    Le conge de Paques est un bloc de quatre jours dans le document, du vendredi
    au lundi. Le retrait des fins de semaine le reduit a deux journees isolees,
    qui doivent donc passer au singulier.
    """
    paques = SchoolEvent(
        summary="Congés pour les élèves, les enseignantes et les enseignants",
        start=date(2027, 3, 26),
        end=date(2027, 3, 30),
        category=EventCategory.HOLIDAY,
    )

    segments = singularize_one_day_summaries(exclude_weekends([paques]))

    assert len(segments) == 2
    for segment in segments:
        assert segment.first_day == segment.last_day
        assert segment.summary.startswith("Congé pour")
