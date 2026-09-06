"""Constantes pour l'integration Calendrier Scolaire Quebecois."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "calendrier_scolaire_quebecois"

PLATFORMS: Final[list[Platform]] = [
    Platform.CALENDAR,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]

# Cles de l'entree de configuration
CONF_SOURCES: Final = "sources"
CONF_REFRESH_INTERVAL: Final = "refresh_interval"
CONF_ENABLE_OCR: Final = "enable_ocr"

# Les cles de serialisation d'une source vivent dans models.py, aupres du code
# qui les lit et les ecrit: ce module importe Platform de Home Assistant, alors
# que models.py doit rester utilisable sans lui.

# Types de source
SOURCE_TYPE_DIRECT_URL: Final = "direct_url"
SOURCE_TYPE_SCHOOL_WEBSITE: Final = "school_website"
SOURCE_TYPE_ICAL: Final = "ical"

SOURCE_TYPES: Final[list[str]] = [
    SOURCE_TYPE_DIRECT_URL,
    SOURCE_TYPE_SCHOOL_WEBSITE,
    SOURCE_TYPE_ICAL,
]

# Services
SERVICE_ADD_SOURCE: Final = "add_source"
SERVICE_REMOVE_SOURCE: Final = "remove_source"
SERVICE_REFRESH_CALENDAR: Final = "refresh_calendar"
SERVICE_PARSE_PDF: Final = "parse_pdf"

# Champs des appels de service. Ces noms sont conserves tels quels pour rester
# compatibles avec les automatisations existantes.
ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_FILE_PATH: Final = "file_path"
ATTR_NAME: Final = "name"
ATTR_SOURCE_ID: Final = "source_id"
ATTR_SOURCE_TYPE: Final = "source_type"
ATTR_SOURCE_URL: Final = "source_url"

# Valeurs par defaut
DEFAULT_NAME: Final = "Calendrier scolaire"
DEFAULT_REFRESH_INTERVAL: Final = 21600  # 6 heures
DEFAULT_ENABLE_OCR: Final = False

# Bornes de l'intervalle de rafraichissement (secondes)
MIN_REFRESH_INTERVAL: Final = 300  # 5 minutes
MAX_REFRESH_INTERVAL: Final = 604800  # 7 jours

# Delais reseau (secondes)
FETCH_TIMEOUT: Final = 60
VALIDATE_TIMEOUT: Final = 15

# Nombre maximal de sources decouvertes automatiquement sur un site scolaire
MAX_DISCOVERED_SOURCES: Final = 10

# Taille maximale d'un telechargement (octets) pour eviter d'epuiser la memoire
MAX_DOWNLOAD_SIZE: Final = 25 * 1024 * 1024  # 25 Mo

# Langues transmises a Tesseract lorsque l'OCR est active
OCR_LANGUAGES: Final = "fra+eng"

# Flux iCalendar publie pour les applications externes (Calendrier d'Apple,
# Google Agenda, Outlook). Le secret est stocke dans ``data`` et non dans les
# options: il ne doit pas pouvoir etre efface par une modification de reglages.
CONF_FEED_SECRET: Final = "feed_secret"
ICS_URL_PREFIX: Final = f"/api/{DOMAIN}/ics"
CONTENT_TYPE_ICS: Final = "text/calendar"

# Version du schema de l'entree de configuration. Aucune migration n'existe:
# incrementer cette valeur exige d'ajouter un async_migrate_entry, sans quoi les
# entrees deja creees ne seront plus chargees.
CONFIG_ENTRY_VERSION: Final = 1
