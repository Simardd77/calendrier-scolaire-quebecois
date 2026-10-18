"""Modeles de donnees pour Calendrier Scolaire Quebecois.

Ce module ne depend pas de Home Assistant afin de rester testable en isolation.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta, tzinfo
from enum import StrEnum

# Longueur maximale d'un titre d'evenement. L'etat d'une entite Home Assistant
# est limite a 255 caracteres, on garde une marge pour les prefixes eventuels.
MAX_SUMMARY_LENGTH = 200

_WHITESPACE_RE = re.compile(r"\s+")
_EMPTY_PARENS_RE = re.compile(r"\(\s*\)")


class EventCategory(StrEnum):
    """Categorie d'un evenement du calendrier scolaire."""

    HOLIDAY = "holiday"
    """Vacances, conge ferie, semaine de relache."""

    PEDAGOGICAL_DAY = "pedagogical_day"
    """Journee pedagogique: pas de classe pour les eleves."""

    TERM_START = "term_start"
    """Rentree scolaire: premiere journee de classe des eleves."""

    TERM_END = "term_end"
    """Fin des classes: derniere journee de classe des eleves."""

    EXAM = "exam"
    """Examen, epreuve ministerielle, evaluation."""

    MEETING = "meeting"
    """Rencontre de parents, remise de bulletin, assemblee."""

    EVENT = "event"
    """Autre evenement scolaire (sortie, photo, portes ouvertes)."""


#: Categories pour lesquelles l'ecole est fermee aux eleves.
#: La rentree et la fin des classes en sont exclues: ce sont des journees de
#: classe, la premiere et la derniere de l'annee.
SCHOOL_CLOSED_CATEGORIES: frozenset[EventCategory] = frozenset(
    {EventCategory.HOLIDAY, EventCategory.PEDAGOGICAL_DAY}
)


def normalize_text(value: str) -> str:
    """Retire les accents et met en minuscules pour faciliter les comparaisons.

    Args:
        value: Texte a normaliser.

    Returns:
        Texte sans accents, en minuscules.
    """
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return without_accents.lower()


def clean_summary(value: str) -> str:
    """Nettoie un titre d'evenement extrait d'un document.

    Reduit les espaces, retire la ponctuation de bordure et tronque sur une
    frontiere de mot.

    Args:
        value: Titre brut.

    Returns:
        Titre nettoye, possiblement vide.
    """
    collapsed = _WHITESPACE_RE.sub(" ", value).strip()
    collapsed = _EMPTY_PARENS_RE.sub("", collapsed).strip()
    # Les parentheses ne sont pas retirees: un libelle comme "Journees
    # pedagogiques (conge pour les eleves)" doit rester equilibre.
    collapsed = collapsed.strip(" \t-–—:;,.|/*_")

    if len(collapsed) <= MAX_SUMMARY_LENGTH:
        return collapsed

    truncated = collapsed[:MAX_SUMMARY_LENGTH]
    if " " in truncated:
        truncated = truncated.rsplit(" ", 1)[0]
    return truncated.rstrip(" \t-–—:;,.|/") + "..."


#: Mises au singulier appliquees au debut d'un titre lorsque l'evenement ne
#: couvre qu'une seule journee. La legende d'un calendrier nomme une categorie de
#: journees, donc au pluriel: "Journees pedagogiques" reste juste pour un bloc de
#: quatre jours, mais decrit mal une journee isolee.
#:
#: Seule la tete du titre est accordee, le complement restant intact: "Conges
#: pour les eleves, les enseignantes et les enseignants" devient "Conge pour les
#: eleves, ...", et non "Conge pour l'eleve, ...". L'adjectif qui suit
#: immediatement le substantif est accorde avec lui, sans quoi on obtiendrait
#: "Journee pedagogiques".
#:
#: La table est volontairement explicite plutot qu'heuristique: les titres
#: viennent d'un PDF quelconque, et un pluriel invariable comme "vacances" ne
#: doit surtout pas etre touche. Une tete absente de la table est laissee telle
#: quelle.
#: Chaque entree donne la tete au pluriel, sans accents ni majuscules, et le
#: nombre de mots a accorder. "Rencontres de parents" n'en accorde qu'un: les
#: parents restent plusieurs. Le singulier est derive du texte d'origine en
#: retirant la marque du pluriel, ce qui preserve les accents et la casse du
#: document plutot que d'imposer une orthographe ecrite ici.
SINGULAR_HEADS: tuple[tuple[str, int], ...] = (
    # Les prefixes les plus longs d'abord: la premiere correspondance gagne.
    ("journees pedagogiques", 2),
    ("rencontres de parents", 1),
    ("journees de classe", 1),
    ("conges", 1),
    ("journees", 1),
    ("fermetures", 1),
    ("rencontres", 1),
    ("examens", 1),
)


def singularize_one_day_summaries(events: list[SchoolEvent]) -> list[SchoolEvent]:
    """Accorde au singulier le titre des evenements d'une seule journee.

    Le decoupage des fins de semaine transforme des plages en journees isolees:
    le conge de Paques, bloc de quatre jours dans le document, ressort en deux
    journees. L'accord est donc decide ici, apres ce decoupage, et non a
    l'extraction ou la duree n'est pas encore definitive.

    Args:
        events: Evenements deja decoupes.

    Returns:
        Nouvelle liste, les titres d'une journee accordes au singulier.
    """
    accordes: list[SchoolEvent] = []

    for event in events:
        if event.first_day != event.last_day:
            accordes.append(event)
            continue

        singulier = _singularize_head(event.summary)
        accordes.append(
            event if singulier == event.summary else replace(event, summary=singulier)
        )

    return accordes


def _singularize_head(summary: str) -> str:
    """Met au singulier la tete d'un titre, si elle figure dans la table.

    Args:
        summary: Titre a accorder.

    Returns:
        Titre accorde, ou le titre d'origine si la tete est inconnue.
    """
    normalise = normalize_text(summary)

    for pluriel, mots_accordes in SINGULAR_HEADS:
        if not normalise.startswith(pluriel):
            continue

        # La tete doit etre un mot entier: "congestion" ne commence pas par le
        # mot "conges" meme si la chaine y ressemble.
        suite = summary[len(pluriel) :]
        if suite and (suite[0].isalpha() or suite[0] == "-"):
            continue

        tete = summary[: len(pluriel)].split(" ")
        for index in range(min(mots_accordes, len(tete))):
            tete[index] = _drop_plural_mark(tete[index])

        return " ".join(tete) + suite

    return summary


def _drop_plural_mark(word: str) -> str:
    """Retire la marque du pluriel d'un mot, en conservant sa casse.

    Args:
        word: Mot au pluriel.

    Returns:
        Mot au singulier, ou inchange s'il ne porte pas de marque.
    """
    if len(word) > 1 and word[-1] in "sxSX":
        return word[:-1]
    return word


#: Cles de serialisation d'une source dans l'entree de configuration. Elles
#: sont definies ici, aupres du seul code qui les lit et les ecrit, pour qu'une
#: modification ne puisse pas desynchroniser lecture et ecriture.
SOURCE_KEY_ID = "id"
SOURCE_KEY_NAME = "name"
SOURCE_KEY_URL = "url"
SOURCE_KEY_TYPE = "type"

#: Nombre d'octets d'alea du secret protegeant le flux iCalendar.
FEED_SECRET_BYTES = 32


@dataclass(frozen=True, slots=True)
class CalendarSource:
    """Une source de calendrier configuree."""

    source_id: str
    name: str
    url: str
    source_type: str

    def as_dict(self) -> dict[str, str]:
        """Serialise la source pour stockage dans l'entree de configuration."""
        return {
            SOURCE_KEY_ID: self.source_id,
            SOURCE_KEY_NAME: self.name,
            SOURCE_KEY_URL: self.url,
            SOURCE_KEY_TYPE: self.source_type,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> CalendarSource:
        """Reconstruit une source depuis un dictionnaire stocke.

        Args:
            data: Dictionnaire contenant au minimum une cle ``url``.

        Returns:
            Instance de CalendarSource.

        Raises:
            ValueError: Si l'URL est absente.
        """
        url = (data.get(SOURCE_KEY_URL) or "").strip()
        if not url:
            raise ValueError("Une source de calendrier requiert une URL")

        return cls(
            source_id=data.get(SOURCE_KEY_ID) or build_source_id(url),
            name=(data.get(SOURCE_KEY_NAME) or url).strip(),
            url=url,
            source_type=data.get(SOURCE_KEY_TYPE) or "direct_url",
        )


def generate_feed_secret(length: int = FEED_SECRET_BYTES) -> str:
    """Genere le secret autorisant l'acces au flux iCalendar.

    Le flux ne peut pas etre protege par un jeton Home Assistant: une
    application de calendrier ne sait pas en presenter un. Le secret voyage donc
    dans l'URL, qui doit etre traitee comme un identifiant.

    Args:
        length: Nombre d'octets d'alea avant encodage url-safe.

    Returns:
        Secret utilisable tel quel dans un chemin d'URL.
    """
    from secrets import token_urlsafe

    return token_urlsafe(length)


def build_source_id(url: str) -> str:
    """Construit un identifiant stable et lisible a partir d'une URL.

    Args:
        url: URL de la source.

    Returns:
        Identifiant deterministe base sur l'URL.
    """
    from hashlib import sha1

    return sha1(url.strip().encode("utf-8")).hexdigest()[:12]


#: Cles de serialisation d'un evenement manuel dans les options de l'entree.
#: Isolees ici, comme SOURCE_KEY_*, pour qu'une modification ne desynchronise
#: pas lecture et ecriture.
MANUAL_KEY_ID = "id"
MANUAL_KEY_SUMMARY = "summary"
MANUAL_KEY_START = "start_date"
MANUAL_KEY_END = "end_date"
MANUAL_KEY_WEEKDAYS = "weekdays"
MANUAL_KEY_START_TIME = "start_time"
MANUAL_KEY_END_TIME = "end_time"
MANUAL_KEY_SKIP_CLOSURES = "skip_closures"


@dataclass(frozen=True, slots=True)
class ManualEvent:
    """Regle d'un evenement saisi a la main, avant generation des occurrences.

    L'evenement est **ponctuel** quand ``weekdays`` est vide: il couvre la seule
    journee ``start_date``. Il est **recurrent** sinon: une occurrence pour
    chaque jour de ``weekdays`` tombant dans la plage inclusive
    [``start_date``, ``end_date``].

    Les jours de semaine suivent la convention de ``date.weekday()`` du reste du
    code: lundi vaut 0, dimanche vaut 6. L'utilisateur saisit des noms, jamais
    ces entiers; la conversion est faite en amont.

    ``end_date`` est **inclusive**: une regle allant jusqu'au 23 juin couvre le
    23 juin. La borne exclusive des ``SchoolEvent`` generes est l'affaire de la
    generation des occurrences, pas de ce modele.

    Les heures sont optionnelles mais solidaires: soit les deux sont presentes
    et l'evenement est horodate, soit aucune et il couvre la journee entiere.
    """

    event_id: str
    summary: str
    start_date: date
    end_date: date
    weekdays: tuple[int, ...] = ()
    start_time: time | None = None
    end_time: time | None = None
    skip_closures: bool = True

    def __post_init__(self) -> None:
        """Valide la coherence de la regle.

        Raises:
            ValueError: Si un champ est incoherent (titre vide, plage inversee,
                jour de semaine hors 0-6, heures non solidaires ou mal ordonnees).
        """
        if not self.summary.strip():
            raise ValueError("Un evenement manuel requiert un titre")

        if self.end_date < self.start_date:
            raise ValueError("end_date ne peut pas preceder start_date")

        for day in self.weekdays:
            if not 0 <= day <= 6:
                raise ValueError(f"Jour de semaine invalide: {day} (attendu 0-6)")

        has_start = self.start_time is not None
        has_end = self.end_time is not None
        if has_start != has_end:
            raise ValueError(
                "start_time et end_time doivent etre fournis ensemble ou pas du tout"
            )
        if has_start and self.end_time <= self.start_time:
            raise ValueError("end_time doit etre strictement posterieur a start_time")

    @property
    def all_day(self) -> bool:
        """Indique si la regle produit des occurrences de journee entiere."""
        return self.start_time is None

    @property
    def is_recurring(self) -> bool:
        """Indique si la regle se repete sur des jours de semaine."""
        return bool(self.weekdays)

    def as_dict(self) -> dict:
        """Serialise la regle pour stockage dans l'entree de configuration.

        Les dates partent en ISO, les heures en "HH:MM", les jours de semaine en
        liste d'entiers. Les heures absentes ne sont pas ecrites.
        """
        data: dict = {
            MANUAL_KEY_ID: self.event_id,
            MANUAL_KEY_SUMMARY: self.summary,
            MANUAL_KEY_START: self.start_date.isoformat(),
            MANUAL_KEY_END: self.end_date.isoformat(),
            MANUAL_KEY_WEEKDAYS: list(self.weekdays),
            MANUAL_KEY_SKIP_CLOSURES: self.skip_closures,
        }
        if self.start_time is not None:
            data[MANUAL_KEY_START_TIME] = self.start_time.strftime("%H:%M")
            data[MANUAL_KEY_END_TIME] = self.end_time.strftime("%H:%M")
        return data

    @classmethod
    def from_dict(cls, data: dict) -> ManualEvent:
        """Reconstruit une regle depuis un dictionnaire stocke.

        Args:
            data: Dictionnaire produit par ``as_dict``, ou saisi par un service.

        Returns:
            Instance de ManualEvent validee.

        Raises:
            ValueError: Si un champ obligatoire manque ou est mal forme.
        """
        summary = (data.get(MANUAL_KEY_SUMMARY) or "").strip()
        start = _parse_iso_date(data.get(MANUAL_KEY_START), MANUAL_KEY_START)
        end = _parse_iso_date(data.get(MANUAL_KEY_END), MANUAL_KEY_END)

        raw_weekdays = data.get(MANUAL_KEY_WEEKDAYS) or []
        try:
            weekdays = tuple(sorted({int(day) for day in raw_weekdays}))
        except (TypeError, ValueError) as err:
            raise ValueError("weekdays doit etre une liste d'entiers") from err

        start_time = _parse_hhmm(data.get(MANUAL_KEY_START_TIME), MANUAL_KEY_START_TIME)
        end_time = _parse_hhmm(data.get(MANUAL_KEY_END_TIME), MANUAL_KEY_END_TIME)

        event_id = data.get(MANUAL_KEY_ID) or build_manual_event_id(
            summary, start, weekdays, start_time
        )

        return cls(
            event_id=event_id,
            summary=summary,
            start_date=start,
            end_date=end,
            weekdays=weekdays,
            start_time=start_time,
            end_time=end_time,
            skip_closures=bool(data.get(MANUAL_KEY_SKIP_CLOSURES, True)),
        )


def _parse_iso_date(value: object, field_name: str) -> date:
    """Lit une date ISO "AAAA-MM-JJ" depuis une valeur stockee ou saisie."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} est requis au format AAAA-MM-JJ")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as err:
        raise ValueError(f"{field_name} invalide: {value!r}") from err


def _parse_hhmm(value: object, field_name: str) -> time | None:
    """Lit une heure "HH:MM", ou None si la valeur est absente."""
    if value is None or value == "":
        return None
    if isinstance(value, time):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field_name} doit etre une heure 'HH:MM'")
    try:
        hours, minutes = value.strip().split(":")
        return time(hour=int(hours), minute=int(minutes))
    except (ValueError, TypeError) as err:
        raise ValueError(f"{field_name} invalide: {value!r}") from err


def build_manual_event_id(
    summary: str,
    start_date: date,
    weekdays: tuple[int, ...],
    start_time: time | None,
) -> str:
    """Construit un identifiant stable et deterministe pour un evenement manuel.

    Fonde sur le contenu de la regle, sur le modele de ``build_source_id``. Deux
    regles identiques produisent le meme identifiant, ce qui evite les doublons.

    Args:
        summary: Titre de l'evenement.
        start_date: Premiere journee de la regle.
        weekdays: Jours de semaine, convention lundi=0.
        start_time: Heure de debut, ou None pour une journee entiere.

    Returns:
        Identifiant deterministe de 12 caracteres.
    """
    from hashlib import sha1

    parts = [
        summary.strip().lower(),
        start_date.isoformat(),
        ",".join(str(day) for day in sorted(weekdays)),
        start_time.strftime("%H:%M") if start_time is not None else "",
    ]
    empreinte = "|".join(parts).encode("utf-8")
    return sha1(empreinte).hexdigest()[:12]


@dataclass(frozen=True, slots=True)
class SchoolEvent:
    """Un evenement du calendrier scolaire.

    Deux representations sont possibles, conformement au composant calendrier
    de Home Assistant:

    - journee entiere: ``start`` et ``end`` sont des ``date``, ``end`` etant
      exclusif (un conge d'une seule journee a ``end == start + 1 jour``);
    - horodate: ``start`` et ``end`` sont des ``datetime`` avec fuseau horaire.
    """

    summary: str
    start: date | datetime
    end: date | datetime
    category: EventCategory = EventCategory.EVENT
    source: str = ""
    description: str = ""
    location: str = ""
    extra: dict[str, str] = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        """Valide la coherence des bornes temporelles.

        Raises:
            ValueError: Si les bornes melangent date et datetime, ou si la fin
                n'est pas strictement posterieure au debut.
        """
        start_is_dt = isinstance(self.start, datetime)
        end_is_dt = isinstance(self.end, datetime)

        if start_is_dt != end_is_dt:
            raise ValueError(
                "start et end doivent etre tous deux des date ou des datetime"
            )

        if self.end <= self.start:
            raise ValueError("end doit etre strictement posterieur a start")

    @property
    def all_day(self) -> bool:
        """Indique si l'evenement couvre des journees entieres."""
        return not isinstance(self.start, datetime)

    @property
    def first_day(self) -> date:
        """Premiere journee couverte par l'evenement."""
        if isinstance(self.start, datetime):
            return self.start.date()
        return self.start

    @property
    def last_day(self) -> date:
        """Derniere journee couverte par l'evenement, incluse."""
        if isinstance(self.end, datetime):
            return self.end.date()
        # end est exclusif pour les evenements de journee entiere.
        return self.end - timedelta(days=1)

    @property
    def closes_school(self) -> bool:
        """Indique si l'ecole est fermee aux eleves pendant l'evenement."""
        return self.category in SCHOOL_CLOSED_CATEGORIES

    @property
    def is_holiday(self) -> bool:
        """Indique s'il s'agit de vacances ou d'un conge."""
        return self.category is EventCategory.HOLIDAY

    def occurs_on(self, day: date) -> bool:
        """Verifie si l'evenement couvre une journee donnee.

        Args:
            day: Journee a tester.

        Returns:
            True si la journee est couverte par l'evenement.
        """
        return self.first_day <= day <= self.last_day

    @property
    def dedup_key(self) -> tuple[str, date, date]:
        """Cle utilisee pour eliminer les doublons entre sources."""
        return (normalize_text(self.summary), self.first_day, self.last_day)

    @property
    def uid(self) -> str:
        """Identifiant stable de l'evenement.

        L'heure entre dans l'identifiant pour les evenements horodates: deux
        evenements de meme titre et meme journee mais a des heures differentes
        (par exemple deux cours manuels le meme mardi) doivent avoir des UID
        distincts, sans quoi un client iCalendar les confondrait. Les evenements
        de journee entiere n'ont pas d'heure: leur UID est inchange.
        """
        from hashlib import sha1

        heure = self.start.strftime("%H:%M") if isinstance(self.start, datetime) else ""
        raw = f"{self.summary}|{self.first_day}|{self.last_day}|{heure}|{self.source}"
        return sha1(normalize_text(raw).encode("utf-8")).hexdigest()[:16]


#: Valeur du champ ``source`` des evenements issus d'une regle manuelle. Elle
#: les distingue des evenements telecharges dans le ``uid`` et les attributs.
MANUAL_EVENT_SOURCE = "manuel"


def expand_manual_event(
    rule: ManualEvent, tz: tzinfo | None = None
) -> list[SchoolEvent]:
    """Genere les occurrences concretes d'une regle manuelle.

    Une regle decrit un motif (jours de semaine, plage, heures); cette fonction
    en produit la liste des ``SchoolEvent`` reels, car ni le flux iCalendar ni
    l'entite calendrier ne gerent une recurrence: chaque occurrence doit
    exister comme evenement distinct.

    - Ponctuelle (``weekdays`` vide): une seule occurrence sur ``start_date``.
    - Recurrente: une occurrence par jour de ``weekdays`` tombant dans la plage
      inclusive [``start_date``, ``end_date``].
    - Journee entiere (aucune heure): ``end`` exclusif vaut le lendemain.
    - Horodatee: ``start`` et ``end`` sont des ``datetime`` localises avec ``tz``.

    Le filtrage des occurrences tombant un jour de fermeture n'est PAS fait ici:
    c'est une etape distincte, qui a besoin du calendrier officiel.

    Args:
        rule: Regle a partir de laquelle generer les occurrences.
        tz: Fuseau applique aux occurrences horodatees. Obligatoire des que la
            regle porte des heures: un ``datetime`` naif serait interprete au
            fuseau de la machine, donnant une heure fausse dans le flux publie.

    Returns:
        Occurrences triees par date de debut.

    Raises:
        ValueError: Si la regle porte des heures et qu'aucun fuseau n'est fourni.
    """
    if not rule.all_day and tz is None:
        raise ValueError(
            "Un fuseau horaire est requis pour generer les occurrences horodatees"
        )

    occurrences = [_build_manual_occurrence(rule, day, tz) for day in _rule_days(rule)]
    occurrences.sort(key=lambda event: event.start)
    return occurrences


def _rule_days(rule: ManualEvent) -> list[date]:
    """Enumere les journees couvertes par une regle.

    Args:
        rule: Regle a parcourir.

    Returns:
        Pour une regle ponctuelle, la seule ``start_date``. Pour une regle
        recurrente, chaque jour de la plage inclusive dont le jour de semaine
        figure dans ``weekdays``.
    """
    if not rule.is_recurring:
        return [rule.start_date]

    jours: list[date] = []
    jour = rule.start_date
    while jour <= rule.end_date:
        if jour.weekday() in rule.weekdays:
            jours.append(jour)
        jour += timedelta(days=1)
    return jours


def _build_manual_occurrence(
    rule: ManualEvent, day: date, tz: tzinfo | None
) -> SchoolEvent:
    """Construit l'occurrence d'une regle pour une journee donnee.

    Args:
        rule: Regle dont provient l'occurrence.
        day: Journee de l'occurrence.
        tz: Fuseau des occurrences horodatees.

    Returns:
        Occurrence sous forme de SchoolEvent.
    """
    if rule.all_day:
        start: date | datetime = day
        end: date | datetime = day + timedelta(days=1)
    else:
        start = datetime.combine(day, rule.start_time, tzinfo=tz)
        end = datetime.combine(day, rule.end_time, tzinfo=tz)

    return SchoolEvent(
        summary=rule.summary,
        start=start,
        end=end,
        category=EventCategory.EVENT,
        source=MANUAL_EVENT_SOURCE,
        extra={
            "manual_event_id": rule.event_id,
            # Chaque occurrence porte le drapeau, pour que le filtrage des jours
            # de fermeture soit autonome, sans relire la regle d'origine.
            "skip_closures": "1" if rule.skip_closures else "0",
        },
    )


def filter_manual_occurrences(
    occurrences: list[SchoolEvent],
    closed_days: frozenset[date],
    term_start: date | None = None,
    term_end: date | None = None,
) -> list[SchoolEvent]:
    """Retire les occurrences manuelles tombant un jour de fermeture scolaire.

    N'agit que sur les occurrences dont le drapeau ``skip_closures`` est vrai,
    lu dans ``extra``. Les autres traversent la fonction intactes, de meme que
    tout evenement qui ne serait pas d'origine manuelle.

    Une occurrence concernee est retiree quand sa journee est:

    - dans ``closed_days`` (conge, journee pedagogique, jour ferie), ou
    - hors de la periode scolaire, lorsque les bornes sont connues: avant
      ``term_start`` ou apres ``term_end``. Une borne a ``None`` est ignoree,
      faute d'information on ne presume aucune fermeture de ce cote.

    Le test porte sur la journee (``first_day``), jamais sur l'heure: un cours de
    10 h un jour de relache est retire quelle que soit son heure.

    Args:
        occurrences: Occurrences a filtrer, typiquement issues de
            ``expand_manual_event``.
        closed_days: Jours de fermeture ponctuelle, pre-calcules une seule fois
            par l'appelant pour un test en temps constant.
        term_start: Premiere journee de l'annee scolaire, ou None si inconnue.
        term_end: Derniere journee de l'annee scolaire, ou None si inconnue.

    Returns:
        Occurrences conservees, dans leur ordre d'origine.
    """
    conserves: list[SchoolEvent] = []

    for event in occurrences:
        if event.extra.get("skip_closures") != "1":
            conserves.append(event)
            continue

        jour = event.first_day
        if jour in closed_days:
            continue
        if term_start is not None and jour < term_start:
            continue
        if term_end is not None and jour > term_end:
            continue

        conserves.append(event)

    return conserves


def deduplicate_events(events: list[SchoolEvent]) -> list[SchoolEvent]:
    """Retire les doublons et trie les evenements par date de debut.

    Deux evenements sont consideres identiques s'ils partagent le meme titre
    normalise et les memes bornes journalieres. Contrairement a une
    deduplication par titre seul, un evenement recurrent a des dates
    differentes est conserve.

    Args:
        events: Evenements a filtrer.

    Returns:
        Nouvelle liste sans doublon, triee chronologiquement.
    """
    seen: set[tuple[str, date, date]] = set()
    unique: list[SchoolEvent] = []

    for event in events:
        key = event.dedup_key
        if key in seen:
            continue
        seen.add(key)
        unique.append(event)

    unique.sort(key=lambda item: (item.first_day, item.last_day, item.summary))
    return unique


#: Categories qui ne sont attribuees qu'a partir d'un mot-cle scolaire reconnu.
#: EventCategory.EVENT en est exclue: c'est la categorie de repli, attribuee a
#: toute ligne datee dont le libelle est simplement plausible.
CALENDAR_SIGNATURE_CATEGORIES: frozenset[EventCategory] = frozenset(
    category for category in EventCategory if category is not EventCategory.EVENT
)


def is_calendar_like(events: list[SchoolEvent]) -> bool:
    """Verifie qu'un lot d'evenements provient bien d'un calendrier scolaire.

    N'importe quel document contenant des dates produit des evenements: un
    reglement, un proces-verbal ou un rapport annuel en fournissent tous. Mais
    seul un calendrier scolaire emploie le vocabulaire du domaine (conge,
    journee pedagogique, relache, rentree, bulletin), qui seul permet de
    depasser la categorie de repli.

    Exiger au moins un evenement type distingue donc un veritable calendrier
    d'un document quelconque qui se trouve contenir des dates.

    Args:
        events: Evenements extraits d'une source.

    Returns:
        True si au moins un evenement porte une categorie scolaire reconnue.
    """
    return any(event.category in CALENDAR_SIGNATURE_CATEGORIES for event in events)


#: Indices de jour rendus par ``date.weekday()`` pour samedi et dimanche.
WEEKEND_DAYS: frozenset[int] = frozenset({5, 6})


def is_weekend(day: date) -> bool:
    """Indique si une journee tombe une fin de semaine.

    Args:
        day: Journee a tester.

    Returns:
        True pour un samedi ou un dimanche.
    """
    return day.weekday() in WEEKEND_DAYS


def split_on_weekends(event: SchoolEvent) -> list[SchoolEvent]:
    """Retire les fins de semaine d'une fermeture d'ecole.

    Un calendrier annonce un conge par ses bornes ("du 23 decembre au 6
    janvier") sans mentionner les fins de semaine qu'il traverse, l'absence de
    classe y etant deja acquise. Presenter la plage telle quelle laisserait
    croire qu'un samedi est un conge scolaire.

    La plage est donc decoupee en segments ne couvrant que des jours de semaine.
    Seules les fermetures sont concernees: un evenement ordinaire annonce un
    samedi est une activite reelle, qui doit etre conservee.

    Args:
        event: Evenement a decouper.

    Returns:
        Segments correspondants. Liste vide si la fermeture ne couvrait que des
        jours de fin de semaine, cas ou elle ne decrit aucune journee de classe.
    """
    if not event.all_day or event.category not in SCHOOL_CLOSED_CATEGORIES:
        return [event]

    segments: list[tuple[date, date]] = []
    segment_start: date | None = None
    day = event.first_day

    while day <= event.last_day:
        if is_weekend(day):
            if segment_start is not None:
                # ``day`` est le premier jour exclu: il fait une fin exclusive.
                segments.append((segment_start, day))
                segment_start = None
        elif segment_start is None:
            segment_start = day

        day += timedelta(days=1)

    if segment_start is not None:
        segments.append((segment_start, event.last_day + timedelta(days=1)))

    # Une plage entierement en semaine ressort inchangee, sans reconstruction.
    if len(segments) == 1 and segments[0] == (event.first_day, event.end):
        return [event]

    return [
        replace(event, start=start, end=end_exclusive)
        for start, end_exclusive in segments
    ]


def exclude_weekends(events: list[SchoolEvent]) -> list[SchoolEvent]:
    """Applique le decoupage des fins de semaine a un lot d'evenements.

    Args:
        events: Evenements consolides.

    Returns:
        Evenements decoupes, dedoublonnes et tries.
    """
    result: list[SchoolEvent] = []

    for event in events:
        result.extend(split_on_weekends(event))

    return deduplicate_events(result)


def merge_extraction_results(
    textual: list[SchoolEvent], structural: list[SchoolEvent]
) -> list[SchoolEvent]:
    """Fusionne les resultats des analyses textuelle et geometrique.

    Lorsque l'analyse geometrique a produit des evenements, elle fait autorite.
    Les calendriers en grille sont accompagnes de notes en prose dont les dates,
    noyees dans des phrases, donnent des titres tronques et sans categorie.
    Seules les mentions typees du texte sont alors conservees, par exemple une
    date de rentree annoncee hors de la grille.

    En l'absence de resultat geometrique, tout le texte est conserve: le
    document est vraisemblablement un calendrier redige.

    Args:
        textual: Evenements issus de l'analyse textuelle.
        structural: Evenements issus de l'analyse geometrique.

    Returns:
        Evenements fusionnes, dedoublonnes et tries.
    """
    if structural:
        textual = [
            event for event in textual if event.category is not EventCategory.EVENT
        ]

    return deduplicate_events(textual + structural)


def _implicit_term_end(term_start: date) -> date:
    """Deduit une fin d'annee scolaire lorsque le document n'en annonce aucune.

    Certains calendriers marquent la rentree mais pas la derniere journee de
    classe. L'annee scolaire quebecoise se terminant en juin, la fin juin qui
    suit la rentree est une borne sure.

    Args:
        term_start: Journee de rentree connue.

    Returns:
        Dernier jour presume de l'annee scolaire.
    """
    year = term_start.year + 1 if term_start.month >= 8 else term_start.year
    return date(year, 6, 30)


def resolve_term_membership(
    day: date, term_starts: list[date], term_ends: list[date]
) -> bool | None:
    """Determine si une journee tombe dans la periode scolaire.

    Un calendrier scolaire ne marque pas les vacances d'ete: juillet et aout ne
    portent aucune indication, l'absence de classe etant sous-entendue par le
    document. La periode scolaire se deduit donc des journees de rentree et de
    fin des classes qu'il annonce.

    Plusieurs annees peuvent cohabiter, un document couvrant de juillet a juin:
    le calendrier 2026-2027 place juillet et aout 2026 avant sa rentree, et ces
    deux mois prolongent l'annee 2025-2026. L'ete n'est donc pas une zone
    absente des documents, c'est l'intervalle entre une fin des classes et la
    rentree suivante.

    Une journee est en periode scolaire s'il existe une rentree anterieure ET
    aucune fin des classes intercalee entre cette rentree et elle. Se contenter
    d'une rentree avant et d'une fin apres declarerait l'ecole ouverte tout
    l'ete separant deux calendriers consecutifs.

    Args:
        day: Journee a evaluer.
        term_starts: Journees de rentree connues, toutes sources confondues.
        term_ends: Journees de fin des classes connues, toutes sources
            confondues.

    Returns:
        True si la journee est dans la periode scolaire, False si elle est hors
        periode, None si le document n'annonce ni rentree ni fin des classes et
        que la question ne peut pas etre tranchee.
    """
    if not term_starts and not term_ends:
        return None

    last_start = max((value for value in term_starts if value <= day), default=None)

    if last_start is None:
        if term_starts:
            # La premiere rentree annoncee par le document est encore a venir.
            return False
        # Aucune rentree annoncee, mais une fin l'est: en periode jusque-la.
        return any(value >= day for value in term_ends)

    # Une fin posterieure a cette rentree et deja passee referme l'annee. C'est
    # ce qui distingue l'ete separant deux calendriers d'un simple creux.
    previous_end = max((value for value in term_ends if value < day), default=None)
    if previous_end is not None and previous_end >= last_start:
        return False

    if any(value >= day for value in term_ends):
        return True

    # Aucune fin ne couvre cette rentree: la periode est bornee a la fin juin
    # suivante, sinon l'ecole serait consideree ouverte l'ete d'apres.
    return day <= _implicit_term_end(last_start)


def resolve_current_term(
    day: date, term_starts: list[date], term_ends: list[date]
) -> tuple[date | None, date | None]:
    """Determine l'annee scolaire a rapporter pour une journee donnee.

    Plusieurs annees peuvent etre chargees ensemble, un document couvrant de
    juillet a juin. Rapporter la premiere rentree et la derniere fin connues
    decrirait l'enveloppe de toutes les annees et non celle en cours: ajouter le
    calendrier de l'annee prochaine deplacerait aussitot la fin annoncee, alors
    que l'annee courante n'a pas change.

    L'annee retenue est donc celle qui contient la journee. A defaut, la
    prochaine annoncee, qui est l'information utile pendant l'ete. A defaut
    encore, la derniere connue.

    Args:
        day: Journee a situer.
        term_starts: Journees de rentree connues, toutes sources confondues.
        term_ends: Journees de fin des classes connues, toutes sources
            confondues.

    Returns:
        Couple (rentree, fin des classes). Chaque element vaut None lorsque
        aucun document ne l'annonce.
    """
    starts = sorted(term_starts)
    ends = sorted(term_ends)

    if not starts:
        if not ends:
            return None, None
        # Aucune rentree annoncee: la fin encore a venir, sinon la derniere.
        return None, min((value for value in ends if value >= day), default=ends[-1])

    def _end_after(start: date) -> date | None:
        """Premiere fin des classes qui suit une rentree."""
        return min((value for value in ends if value >= start), default=None)

    last_start = max((value for value in starts if value <= day), default=None)

    if last_start is not None:
        end = _end_after(last_start)
        limit = end if end is not None else _implicit_term_end(last_start)
        if day <= limit:
            return last_start, end

    next_start = min((value for value in starts if value > day), default=None)
    if next_start is not None:
        return next_start, _end_after(next_start)

    return starts[-1], _end_after(starts[-1])
