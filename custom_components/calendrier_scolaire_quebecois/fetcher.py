"""Recuperation HTTP des sources de calendrier."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import aiohttp

from .const import MAX_DISCOVERED_SOURCES, MAX_DOWNLOAD_SIZE

_LOGGER = logging.getLogger(__name__)

# Certains sites d'etablissements refusent les requetes sans agent utilisateur.
USER_AGENT = "Mozilla/5.0 (compatible; HomeAssistant CalendrierScolaireQuebecois)"

CHUNK_SIZE = 64 * 1024

_HREF_RE = re.compile(r"""href\s*=\s*["']([^"'>\s]+)["']""", re.IGNORECASE)
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
_BLOCK_TAG_RE = re.compile(
    r"</?(p|div|br|tr|td|th|li|h[1-6]|table|section|article)\b[^>]*>",
    re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]+>")
_BLANK_LINES_RE = re.compile(r"\n\s*\n+")

# Extensions de fichier considerees comme des sources de calendrier.
_CALENDAR_EXTENSIONS = (".pdf", ".ics", ".ical", ".ifb")

# Indices textuels privilegies dans une URL de calendrier.
_CALENDAR_HINTS = (
    "calendrier",
    "calendar",
    "scolaire",
    "school",
    "horaire",
    "annuel",
    "rentree",
)


class FetchError(Exception):
    """Echec de recuperation d'une source."""


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Resultat d'un telechargement.

    Attributes:
        url: URL finale, apres redirections.
        content: Contenu binaire recupere.
        content_type: En-tete Content-Type renvoye par le serveur.
    """

    url: str
    content: bytes
    content_type: str


async def fetch(session: aiohttp.ClientSession, url: str, timeout: int) -> FetchResult:
    """Telecharge une URL en bornant la taille de la reponse.

    Args:
        session: Session HTTP partagee fournie par Home Assistant.
        url: URL a recuperer.
        timeout: Delai total en secondes.

    Returns:
        Contenu telecharge et metadonnees associees.

    Raises:
        FetchError: Si la requete echoue, renvoie un code non 200, ou depasse
            la taille maximale autorisee.
    """
    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=timeout),
            headers={"User-Agent": USER_AGENT},
        ) as response:
            if response.status != 200:
                raise FetchError(f"HTTP {response.status} pour {url}")

            chunks: list[bytes] = []
            size = 0

            async for chunk in response.content.iter_chunked(CHUNK_SIZE):
                size += len(chunk)
                if size > MAX_DOWNLOAD_SIZE:
                    raise FetchError(
                        f"Contenu trop volumineux pour {url} "
                        f"(limite {MAX_DOWNLOAD_SIZE} octets)"
                    )
                chunks.append(chunk)

            return FetchResult(
                url=str(response.url),
                content=b"".join(chunks),
                content_type=response.headers.get("Content-Type", ""),
            )

    except FetchError:
        raise
    except aiohttp.ClientError as err:
        raise FetchError(f"Erreur reseau pour {url}: {err}") from err
    except TimeoutError as err:
        raise FetchError(f"Delai depasse pour {url}") from err


def decode_text(content: bytes, content_type: str) -> str:
    """Decode un contenu textuel en respectant le jeu de caracteres annonce.

    Args:
        content: Contenu binaire.
        content_type: En-tete Content-Type de la reponse.

    Returns:
        Texte decode. Les octets invalides sont remplaces plutot que de faire
        echouer l'analyse complete.
    """
    charset = "utf-8"

    if "charset=" in content_type.lower():
        charset = content_type.lower().split("charset=", 1)[1].split(";")[0].strip()

    try:
        return content.decode(charset, errors="replace")
    except LookupError:
        return content.decode("utf-8", errors="replace")


def html_to_text(html: str) -> str:
    """Convertit du HTML en texte, une information par ligne.

    Les balises de bloc deviennent des sauts de ligne afin que l'analyseur
    d'evenements retrouve la correspondance entre une date et son libelle.

    Args:
        html: Source HTML.

    Returns:
        Texte extrait.
    """
    without_scripts = _SCRIPT_STYLE_RE.sub(" ", html)
    with_breaks = _BLOCK_TAG_RE.sub("\n", without_scripts)
    without_tags = _TAG_RE.sub(" ", with_breaks)

    unescaped = (
        without_tags.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )

    lines = [line.strip() for line in unescaped.splitlines()]
    return _BLANK_LINES_RE.sub("\n", "\n".join(line for line in lines if line))


def find_calendar_links(html: str, base_url: str) -> list[str]:
    """Recherche les liens vers des documents de calendrier dans une page.

    Args:
        html: Source HTML de la page.
        base_url: URL de la page, utilisee pour resoudre les liens relatifs.

    Returns:
        URL absolues, sans doublon, limitees a MAX_DISCOVERED_SOURCES. Les
        liens dont l'adresse evoque un calendrier sont prioritaires.
    """
    hinted: list[str] = []
    others: list[str] = []
    seen: set[str] = set()

    for match in _HREF_RE.finditer(html):
        href = match.group(1).strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue

        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)

        if parsed.scheme not in ("http", "https"):
            continue
        if not parsed.path.lower().endswith(_CALENDAR_EXTENSIONS):
            continue
        if absolute in seen:
            continue

        seen.add(absolute)
        lowered = absolute.lower()

        if any(hint in lowered for hint in _CALENDAR_HINTS):
            hinted.append(absolute)
        else:
            others.append(absolute)

    return (hinted + others)[:MAX_DISCOVERED_SOURCES]
