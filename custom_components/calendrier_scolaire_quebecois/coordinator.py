"""Coordinateur de mise a jour pour Calendrier Scolaire Quebecois."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ENABLE_OCR,
    CONF_REFRESH_INTERVAL,
    CONF_SOURCES,
    DEFAULT_ENABLE_OCR,
    DEFAULT_REFRESH_INTERVAL,
    DOMAIN,
    FETCH_TIMEOUT,
    OCR_LANGUAGES,
    SOURCE_TYPE_SCHOOL_WEBSITE,
    VALIDATE_TIMEOUT,
)
from .fetcher import (
    FetchError,
    FetchResult,
    decode_text,
    fetch,
    find_calendar_links,
    html_to_text,
)
from .models import (
    CalendarSource,
    EventCategory,
    SchoolEvent,
    exclude_weekends,
    singularize_one_day_summaries,
    is_calendar_like,
    merge_extraction_results,
    resolve_current_term,
    resolve_term_membership,
)
from .parsers import DependencyMissingError, ParserError
from .parsers.dates import school_year_start_for
from .parsers.events import detect_school_year, extract_events_from_text
from .parsers.grid import extract_events_from_grid
from .parsers.ical import looks_like_ical, parse_ical
from .parsers.ocr import extract_text_via_ocr
from .parsers.pdf import looks_like_pdf, read_pdf

_LOGGER = logging.getLogger(__name__)

type SchoolCalendarConfigEntry = ConfigEntry[SchoolCalendarCoordinator]


def event_bounds(event: SchoolEvent) -> tuple[datetime, datetime]:
    """Convertit les bornes d'un evenement en horodatages localises.

    Args:
        event: Evenement a convertir.

    Returns:
        Couple (debut, fin) sous forme de datetime avec fuseau horaire, la fin
        etant exclusive.
    """
    if event.all_day:
        return (
            dt_util.start_of_local_day(event.start),
            dt_util.start_of_local_day(event.end),
        )

    # Les evenements horodates sont deja localises par les analyseurs.
    return event.start, event.end  # type: ignore[return-value]


@dataclass(slots=True)
class CalendarData:
    """Donnees produites par un cycle de mise a jour.

    Attributes:
        events: Evenements dedoublonnes et tries.
        source_errors: Message d'erreur par nom de source en echec.
        sources_total: Nombre de sources configurees.
    """

    events: list[SchoolEvent] = field(default_factory=list)
    source_errors: dict[str, str] = field(default_factory=dict)
    sources_total: int = 0

    @property
    def sources_ok(self) -> int:
        """Nombre de sources traitees sans erreur."""
        return max(self.sources_total - len(self.source_errors), 0)

    def events_between(self, start: datetime, end: datetime) -> list[SchoolEvent]:
        """Selectionne les evenements chevauchant une periode.

        Args:
            start: Debut de la periode.
            end: Fin de la periode, exclusive.

        Returns:
            Evenements chevauchant la periode, tries par debut.
        """
        matching: list[tuple[datetime, SchoolEvent]] = []

        for event in self.events:
            event_start, event_end = event_bounds(event)
            if event_start < end and event_end > start:
                matching.append((event_start, event))

        matching.sort(key=lambda item: item[0])
        return [event for _, event in matching]

    def events_on(self, day: date) -> list[SchoolEvent]:
        """Selectionne les evenements couvrant une journee.

        Args:
            day: Journee a inspecter.

        Returns:
            Evenements couvrant cette journee.
        """
        return [event for event in self.events if event.occurs_on(day)]

    @property
    def term_starts(self) -> list[date]:
        """Journees de rentree annoncees, triees."""
        return sorted(
            event.first_day
            for event in self.events
            if event.category is EventCategory.TERM_START
        )

    @property
    def term_ends(self) -> list[date]:
        """Journees de fin des classes annoncees, triees."""
        return sorted(
            event.last_day
            for event in self.events
            if event.category is EventCategory.TERM_END
        )

    def is_within_term(self, day: date) -> bool | None:
        """Determine si une journee tombe dans la periode scolaire.

        Args:
            day: Journee a evaluer.

        Returns:
            True dans la periode scolaire, False hors periode, None si le
            document ne permet pas de trancher.
        """
        return resolve_term_membership(day, self.term_starts, self.term_ends)

    def current_term(self, day: date) -> tuple[date | None, date | None]:
        """Dates de l'annee scolaire a rapporter pour une journee.

        Plusieurs annees pouvant etre chargees ensemble, ce sont les dates de
        l'annee situant la journee qui sont retournees, et non l'enveloppe de
        toutes les annees connues.

        Args:
            day: Journee a situer.

        Returns:
            Couple (rentree, fin des classes), chaque element pouvant etre None.
        """
        return resolve_current_term(day, self.term_starts, self.term_ends)

    def next_event(self, now: datetime) -> SchoolEvent | None:
        """Retourne l'evenement en cours, ou le prochain a venir.

        Args:
            now: Horodatage de reference, localise.

        Returns:
            Evenement le plus pertinent, ou None si aucun.
        """
        candidates: list[tuple[datetime, SchoolEvent]] = []

        for event in self.events:
            event_start, event_end = event_bounds(event)
            if event_end > now:
                candidates.append((event_start, event))

        if not candidates:
            return None

        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]


# --- Fonctions synchrones destinees a un executor ----------------------------
# L'analyse d'un PDF et l'extraction par expressions regulieres sont couteuses
# en CPU. Les executer dans la boucle asyncio gelerait Home Assistant.


def _events_from_text(
    text: str, source_name: str, fallback_year: int
) -> list[SchoolEvent]:
    """Extrait les evenements d'un texte deja decode.

    Args:
        text: Texte du document.
        source_name: Nom de la source.
        fallback_year: Annee scolaire a utiliser si le document ne l'annonce pas.

    Returns:
        Evenements extraits.
    """
    school_year = detect_school_year(text) or fallback_year
    return extract_events_from_text(text, source_name, school_year)


def _events_from_pdf(
    content: bytes,
    source_name: str,
    fallback_year: int,
    enable_ocr: bool,
) -> list[SchoolEvent]:
    """Extrait les evenements d'un PDF par les deux strategies disponibles.

    L'analyse textuelle traite les calendriers rediges en phrases. L'analyse
    geometrique traite les calendriers presentes en grille, ou le sens de chaque
    journee est porte par une forme entourant le chiffre. Les deux sont
    appliquees puis fusionnees: un document peut combiner les deux formes, et un
    document qui n'en releve que d'une ne produit simplement rien avec l'autre.

    Args:
        content: Contenu binaire du PDF.
        source_name: Nom de la source.
        fallback_year: Annee scolaire par defaut.
        enable_ocr: Autorise le repli OCR pour les PDF numerises.

    Returns:
        Evenements extraits, dedoublonnes.

    Raises:
        DependencyMissingError: Si pdfplumber est absent.
        ParserError: Si le document est illisible.
    """
    document = read_pdf(content)

    if not document.has_text:
        if not enable_ocr:
            _LOGGER.warning(
                "Aucun texte extrait de '%s': le PDF est probablement numerise. "
                "Activez l'OCR dans les options si les binaires tesseract et "
                "poppler sont installes",
                source_name,
            )
            return []

        _LOGGER.debug("Repli OCR pour '%s'", source_name)
        return _events_from_text(
            extract_text_via_ocr(content, OCR_LANGUAGES), source_name, fallback_year
        )

    school_year = detect_school_year(document.text) or fallback_year
    textual = extract_events_from_text(document.text, source_name, school_year)

    structural: list[SchoolEvent] = []

    for page in document.pages:
        structural.extend(
            extract_events_from_grid(page.words, page.shapes, source_name, school_year)
        )

    merged = merge_extraction_results(textual, structural)

    if not merged:
        _LOGGER.warning(
            "Du texte a ete extrait de '%s' mais aucun evenement n'a ete "
            "reconnu, ni par mots-cles ni par analyse de grille. Le service "
            "parse_pdf permet d'inspecter le document",
            source_name,
        )
    else:
        _LOGGER.debug(
            "'%s': %d evenement(s) par le texte, %d par la grille, %d apres " "fusion",
            source_name,
            len(textual),
            len(structural),
            len(merged),
        )

    return merged


def _events_from_pdf_file(
    path: str, source_name: str, fallback_year: int, enable_ocr: bool
) -> list[SchoolEvent]:
    """Lit un PDF sur disque puis en extrait les evenements.

    Args:
        path: Chemin du fichier.
        source_name: Nom attribue a la source.
        fallback_year: Annee scolaire par defaut.
        enable_ocr: Autorise le repli OCR.

    Returns:
        Evenements extraits.

    Raises:
        OSError: Si le fichier est illisible.
    """
    return _events_from_pdf(
        Path(path).read_bytes(), source_name, fallback_year, enable_ocr
    )


# --- Analyse partagee --------------------------------------------------------


async def async_extract_events(
    hass: HomeAssistant,
    source_name: str,
    result: FetchResult,
    *,
    fallback_year: int,
    enable_ocr: bool,
) -> list[SchoolEvent]:
    """Analyse un contenu telecharge selon son type reel.

    Le type est determine par la signature binaire du contenu plutot que par
    l'extension de l'URL, souvent absente ou trompeuse.

    Cette fonction est independante du coordinateur afin que le flux de
    configuration puisse valider une source avant de la retenir, sans dupliquer
    la logique d'analyse.

    Args:
        hass: Instance Home Assistant, pour deleguer le travail CPU.
        source_name: Nom de la source d'origine.
        result: Contenu telecharge.
        fallback_year: Annee scolaire a utiliser si le document ne l'annonce pas.
        enable_ocr: Autorise le repli OCR.

    Returns:
        Evenements extraits.

    Raises:
        ParserError: Si une dependance requise est absente ou si le document
            est illisible.
    """
    content = result.content

    if not content:
        _LOGGER.debug("Contenu vide pour '%s'", source_name)
        return []

    if looks_like_pdf(content):
        return await hass.async_add_executor_job(
            _events_from_pdf, content, source_name, fallback_year, enable_ocr
        )

    if looks_like_ical(content):
        return await hass.async_add_executor_job(
            parse_ical, content, source_name, dt_util.DEFAULT_TIME_ZONE
        )

    text = decode_text(content, result.content_type)
    return await hass.async_add_executor_job(
        _events_from_text, html_to_text(text), source_name, fallback_year
    )


async def async_probe_source(
    hass: HomeAssistant,
    url: str,
    source_type: str,
    *,
    enable_ocr: bool = DEFAULT_ENABLE_OCR,
    timeout: int = VALIDATE_TIMEOUT,
) -> list[SchoolEvent]:
    """Analyse une URL pour verifier qu'elle fournit un calendrier scolaire.

    Sert au flux de configuration: une adresse joignable ne prouve pas qu'elle
    pointe vers un calendrier. Le document est donc reellement telecharge et
    analyse avant d'etre retenu comme source.

    Pour un site d'etablissement, les documents decouverts sont essayes l'un
    apres l'autre et l'analyse s'arrete au premier qui porte des marqueurs de
    calendrier: valider la source ne necessite pas de tout telecharger.

    Args:
        hass: Instance Home Assistant.
        url: Adresse a valider.
        source_type: Type de source declare par l'utilisateur.
        enable_ocr: Autorise le repli OCR pendant la validation.
        timeout: Delai reseau. Plus court que celui d'un cycle normal, pour ne
            pas figer le formulaire de configuration.

    Returns:
        Evenements extraits, vide si l'adresse ne fournit rien d'exploitable.

    Raises:
        FetchError: Si l'adresse principale est inaccessible.
        ParserError: Si le document principal est illisible.
    """
    session = async_get_clientsession(hass)
    fallback_year = school_year_start_for(dt_util.now().date())

    result = await fetch(session, url, timeout)

    if source_type != SOURCE_TYPE_SCHOOL_WEBSITE:
        return await async_extract_events(
            hass,
            url,
            result,
            fallback_year=fallback_year,
            enable_ocr=enable_ocr,
        )

    html = decode_text(result.content, result.content_type)
    links = find_calendar_links(html, result.url)

    if not links:
        return await hass.async_add_executor_job(
            _events_from_text, html_to_text(html), url, fallback_year
        )

    for link in links:
        try:
            document = await fetch(session, link, timeout)
            events = await async_extract_events(
                hass,
                link,
                document,
                fallback_year=fallback_year,
                enable_ocr=enable_ocr,
            )
        except (FetchError, ParserError) as err:
            _LOGGER.debug("Document ignore pendant la validation (%s): %s", link, err)
            continue

        if is_calendar_like(events):
            return events

    return []


class SchoolCalendarCoordinator(DataUpdateCoordinator[CalendarData]):
    """Recupere et analyse les sources de calendrier scolaire."""

    config_entry: SchoolCalendarConfigEntry

    def __init__(self, hass: HomeAssistant, entry: SchoolCalendarConfigEntry) -> None:
        """Initialise le coordinateur.

        Args:
            hass: Instance Home Assistant.
            entry: Entree de configuration associee.
        """
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{entry.title}",
            update_interval=timedelta(
                seconds=self._read_option(
                    entry, CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL
                )
            ),
        )

    @staticmethod
    def _read_option(entry: ConfigEntry, key: str, default: object) -> object:
        """Lit une valeur dans les options, avec repli sur les donnees.

        Les entrees creees avant la migration conservent leurs reglages dans
        ``data``.

        Args:
            entry: Entree de configuration.
            key: Cle recherchee.
            default: Valeur par defaut.

        Returns:
            Valeur trouvee ou valeur par defaut.
        """
        if key in entry.options:
            return entry.options[key]
        return entry.data.get(key, default)

    @property
    def enable_ocr(self) -> bool:
        """Indique si le repli OCR est autorise."""
        return bool(
            self._read_option(self.config_entry, CONF_ENABLE_OCR, DEFAULT_ENABLE_OCR)
        )

    @property
    def sources(self) -> list[CalendarSource]:
        """Sources de calendrier configurees.

        Returns:
            Liste des sources valides. Une entree malformee est ignoree avec un
            avertissement plutot que de faire echouer tout le cycle.
        """
        raw = self._read_option(self.config_entry, CONF_SOURCES, []) or []
        sources: list[CalendarSource] = []

        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                sources.append(CalendarSource.from_dict(item))
            except ValueError as err:
                _LOGGER.warning("Source de calendrier ignoree: %s", err)

        return sources

    @property
    def fallback_school_year(self) -> int:
        """Annee scolaire deduite de la date courante locale."""
        return school_year_start_for(dt_util.now().date())

    async def _async_update_data(self) -> CalendarData:
        """Recupere et analyse toutes les sources configurees.

        Returns:
            Donnees consolidees du calendrier.

        Raises:
            UpdateFailed: Si toutes les sources configurees ont echoue.
        """
        sources = self.sources

        if not sources:
            _LOGGER.debug("Aucune source configuree pour %s", self.config_entry.title)
            return CalendarData()

        results = await asyncio.gather(
            *(self._async_load_source(source) for source in sources),
            return_exceptions=True,
        )

        events: list[SchoolEvent] = []
        errors: dict[str, str] = {}

        for source, result in zip(sources, results, strict=True):
            if isinstance(result, BaseException):
                errors[source.name] = str(result)
                _LOGGER.warning("Source '%s' en echec: %s", source.name, result)
                continue
            events.extend(result)

        if len(errors) == len(sources):
            raise UpdateFailed(
                "Aucune source n'a pu etre traitee: "
                + "; ".join(f"{name}: {msg}" for name, msg in errors.items())
            )

        # Les fins de semaine sont retirees des fermetures: un calendrier
        # annonce un conge par ses dates, sans distinguer les samedis et
        # dimanches qu'il traverse. L'accord du titre vient ensuite, le
        # decoupage etant ce qui produit les journees isolees.
        data = CalendarData(
            events=singularize_one_day_summaries(exclude_weekends(events)),
            source_errors=errors,
            sources_total=len(sources),
        )

        _LOGGER.debug(
            "%d evenement(s) depuis %d/%d source(s) pour %s",
            len(data.events),
            data.sources_ok,
            data.sources_total,
            self.config_entry.title,
        )

        return data

    async def _async_load_source(self, source: CalendarSource) -> list[SchoolEvent]:
        """Recupere et analyse une source.

        Args:
            source: Source a traiter.

        Returns:
            Evenements extraits de cette source.

        Raises:
            FetchError: Si le telechargement echoue.
            ParserError: Si l'analyse echoue.
        """
        session = async_get_clientsession(self.hass)

        if source.source_type == SOURCE_TYPE_SCHOOL_WEBSITE:
            return await self._async_load_website(source)

        result = await fetch(session, source.url, FETCH_TIMEOUT)
        return await self._async_parse_content(source.name, result)

    async def _async_load_website(self, source: CalendarSource) -> list[SchoolEvent]:
        """Analyse un site scolaire en cherchant les documents de calendrier.

        La page est d'abord inspectee a la recherche de liens vers des PDF ou
        des fichiers iCalendar. A defaut, le texte de la page est analyse
        directement.

        Args:
            source: Source de type site scolaire.

        Returns:
            Evenements extraits des documents trouves ou de la page elle-meme.

        Raises:
            FetchError: Si la page principale est inaccessible.
        """
        session = async_get_clientsession(self.hass)
        page = await fetch(session, source.url, FETCH_TIMEOUT)
        html = decode_text(page.content, page.content_type)

        links = find_calendar_links(html, page.url)

        if not links:
            _LOGGER.debug(
                "Aucun document de calendrier trouve sur %s, analyse de la page",
                source.url,
            )
            return await self.hass.async_add_executor_job(
                _events_from_text,
                html_to_text(html),
                source.name,
                self.fallback_school_year,
            )

        _LOGGER.debug("%d document(s) decouvert(s) sur %s", len(links), source.url)

        events: list[SchoolEvent] = []

        for link in links:
            try:
                document = await fetch(session, link, FETCH_TIMEOUT)
                found = await self._async_parse_content(source.name, document)
            except (FetchError, ParserError) as err:
                _LOGGER.warning("Document decouvert ignore (%s): %s", link, err)
                continue

            # Les liens sont retenus sur leur extension: la page peut heberger
            # un reglement ou un proces-verbal, dont les dates produiraient de
            # faux evenements. Seuls les documents portant des marqueurs de
            # calendrier sont conserves.
            if not is_calendar_like(found):
                _LOGGER.debug("Document ecarte, aucun marqueur de calendrier: %s", link)
                continue

            events.extend(found)

        return events

    async def _async_parse_content(
        self, source_name: str, result: FetchResult
    ) -> list[SchoolEvent]:
        """Analyse un contenu telecharge selon les reglages de cette entree.

        Args:
            source_name: Nom de la source d'origine.
            result: Contenu telecharge.

        Returns:
            Evenements extraits.

        Raises:
            ParserError: Si une dependance requise est absente ou si le
                document est illisible.
        """
        return await async_extract_events(
            self.hass,
            source_name,
            result,
            fallback_year=self.fallback_school_year,
            enable_ocr=self.enable_ocr,
        )

    async def async_parse_pdf_file(self, file_path: str) -> list[SchoolEvent]:
        """Analyse un PDF present sur le systeme de fichiers.

        Args:
            file_path: Chemin absolu du fichier.

        Returns:
            Evenements extraits du document.

        Raises:
            ServiceValidationError: Si le chemin n'est pas autorise, absent, ou
                si le document est illisible.
        """
        if not self.hass.config.is_allowed_path(file_path):
            raise ServiceValidationError(
                f"Le chemin '{file_path}' n'est pas autorise. Ajoutez son "
                "repertoire a allowlist_external_dirs dans configuration.yaml"
            )

        try:
            return await self.hass.async_add_executor_job(
                _events_from_pdf_file,
                file_path,
                Path(file_path).name,
                self.fallback_school_year,
                self.enable_ocr,
            )
        except (OSError, DependencyMissingError, ParserError) as err:
            raise ServiceValidationError(
                f"Analyse de '{file_path}' impossible: {err}"
            ) from err
