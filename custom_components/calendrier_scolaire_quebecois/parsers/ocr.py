"""Extraction de texte par OCR pour les PDF numerises.

Cette fonctionnalite est facultative et desactivee par defaut. Elle requiert
des paquets Python (pytesseract, pdf2image, pillow) ainsi que des binaires
systeme (tesseract, poppler) qui ne sont pas presents dans les images Home
Assistant OS et Container. Elle n'est donc utilisable que sur une installation
ou ces binaires ont ete ajoutes manuellement.

Les fonctions de ce module sont synchrones et bloquantes: elles doivent etre
appelees depuis un executor.

Ce module ne depend pas de Home Assistant.
"""

from __future__ import annotations

import logging

from . import DependencyMissingError, ParserError

_LOGGER = logging.getLogger(__name__)

# Resolution de rasterisation. 300 ppp est le compromis usuel entre qualite de
# reconnaissance et consommation memoire.
OCR_DPI = 300

# Au-dela de cette limite, la rasterisation d'un PDF epuiserait la memoire
# disponible d'une instance Home Assistant modeste.
MAX_OCR_PAGES = 20


def extract_text_via_ocr(data: bytes, languages: str) -> str:
    """Rasterise un PDF puis en extrait le texte par OCR.

    Args:
        data: Contenu binaire du PDF.
        languages: Langues transmises a tesseract, par exemple "fra+eng".

    Returns:
        Texte reconnu, une page par bloc.

    Raises:
        DependencyMissingError: Si un paquet requis est absent.
        ParserError: Si la rasterisation ou la reconnaissance echoue.
    """
    try:
        import pytesseract
        from pdf2image import convert_from_bytes
    except ImportError as err:
        raise DependencyMissingError(
            "pytesseract / pdf2image", "l'extraction OCR"
        ) from err

    try:
        images = convert_from_bytes(data, dpi=OCR_DPI)
    except Exception as err:
        raise ParserError(f"Rasterisation du PDF impossible: {err}") from err

    if len(images) > MAX_OCR_PAGES:
        _LOGGER.warning(
            "PDF de %d pages: seules les %d premieres seront traitees par OCR",
            len(images),
            MAX_OCR_PAGES,
        )
        images = images[:MAX_OCR_PAGES]

    fragments: list[str] = []

    for page_number, image in enumerate(images, start=1):
        try:
            fragments.append(
                pytesseract.image_to_string(_preprocess(image), lang=languages)
            )
        except Exception as err:  # noqa: BLE001 - une page ratee n'arrete pas le reste
            _LOGGER.debug("OCR echoue sur la page %d: %s", page_number, err)

    if not fragments:
        raise ParserError("Aucune page n'a pu etre traitee par OCR")

    return "\n".join(fragments)


def _preprocess(image: object) -> object:
    """Ameliore le contraste d'une image avant reconnaissance.

    Args:
        image: Image PIL.

    Returns:
        Image pretraitee, ou l'image d'origine si le pretraitement echoue.
    """
    try:
        from PIL import ImageEnhance

        grayscale = image.convert("L")  # type: ignore[attr-defined]
        return ImageEnhance.Contrast(grayscale).enhance(2.0)
    except Exception:  # noqa: BLE001 - le pretraitement est une optimisation
        return image
