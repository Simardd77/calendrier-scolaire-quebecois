"""Analyse geometrique des calendriers scolaires presentes en grille.

Les centres de services scolaires quebecois publient leur calendrier sous forme
de douze grilles mensuelles ou le sens de chaque journee est encode
graphiquement: un cercle autour du chiffre signifie un conge, un carre une
journee pedagogique, un losange une journee pedagogique pour force majeure.
Certains etablissements utilisent plutot un fond de couleur.

La couche texte ne contient que des chiffres nus: aucun analyseur textuel ne
peut reussir. Ce module travaille donc sur la geometrie.

Principe directeur: le document porte sa propre legende. Les formes situees
hors des grilles sont relevees avec le texte qui les accompagne, ce qui produit
une table de correspondance forme -> signification propre au document. Chaque
forme de la grille est ensuite rattachee a la forme de legende la plus proche.
Aucune dimension n'est codee en dur, ce qui permet de traiter les variantes
d'un centre de services a l'autre.

Ce module ne depend ni de Home Assistant ni de pdfplumber: il recoit des
dictionnaires simples, ce qui le rend testable avec des donnees synthetiques.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

from ..models import (
    EventCategory,
    SchoolEvent,
    clean_summary,
    deduplicate_events,
    normalize_text,
)
from .dates import resolve_year
from .events import classify

_LOGGER = logging.getLogger(__name__)

#: Noms de mois complets acceptes comme en-tete de grille, sous forme
#: normalisee. Les abreviations sont volontairement exclues: un en-tete de
#: grille est toujours ecrit en entier.
MONTH_HEADERS: dict[str, int] = {
    "janvier": 1,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "decembre": 12,
}

# Encombrement plausible d'un marqueur entourant un chiffre, en points PDF.
MIN_MARKER_SIZE = 7.0
MAX_MARKER_SIZE = 32.0
MAX_RANGE_MARKER_WIDTH = 180.0

# Ecart maximal, en points, entre une forme de grille et une forme de legende
# pour les considerer identiques.
MAX_PROTOTYPE_DISTANCE = 3.0

# Ecart maximal entre deux centroides normalises pour admettre qu'il s'agit de
# la meme forme. Un triangle pointant vers le haut et un triangle pointant vers
# le bas ont des centroides separes de 0,5: la marge est confortable.
CENTROID_TOLERANCE = 0.12

# Une meme signification ne peut pas marquer autant de journees dans une annee
# scolaire: au-dela, il s'agit d'un ombrage structurel comme la teinte des fins
# de semaine, pas d'un marqueur d'evenement.
MAX_DAYS_PER_PROTOTYPE = 60

# Ecart horizontal au-dela duquel le texte suivant appartient a une autre
# colonne que le libelle de legende.
LEGEND_TEXT_GAP = 25.0

# Tolerance verticale pour considerer qu'un mot accompagne un en-tete de mois.
HEADER_YEAR_LINE_TOLERANCE = 7.0

# Part du chevauchement vertical maximal en deca de laquelle un mot est
# considere comme appartenant a une autre ligne que le libelle.
MIN_LABEL_OVERLAP_RATIO = 0.5

# Valeurs de repli lorsque la disposition ne permet pas de les deduire.
DEFAULT_BLOCK_HEIGHT = 140.0
DEFAULT_COLUMN_HALF_WIDTH = 95.0

# Nombre minimal de numeros de jour qu'une vraie grille mensuelle doit contenir.
# Un mois compte au moins vingt jours ouvrables; une note de bas de page citant
# un mois n'en contient aucun. Ce seuil ecarte les faux en-tetes, qui sinon
# faussent le calcul de la largeur des colonnes et tronquent les grilles.
MIN_DAY_WORDS_PER_REGION = 15

WEEKEND_DAYS = (5, 6)


def _center(box: dict) -> tuple[float, float]:
    """Retourne le centre d'un objet positionne.

    Args:
        box: Dictionnaire contenant x0, x1, top et bottom.

    Returns:
        Couple (x, y) du centre.
    """
    return ((box["x0"] + box["x1"]) / 2, (box["top"] + box["bottom"]) / 2)


def _color_key(value: object) -> str:
    """Normalise une couleur pdfplumber en cle comparable.

    Args:
        value: Couleur, scalaire pour un niveau de gris ou sequence pour RGB
            et CMJN.

    Returns:
        Representation stable de la couleur.
    """
    if value is None:
        return "none"
    if isinstance(value, (int, float)):
        return f"g{float(value):.3f}"
    if isinstance(value, (list, tuple)):
        return "c" + ",".join(f"{float(component):.3f}" for component in value)
    return str(value)


def _vertices(shape: dict) -> list[tuple[float, float]]:
    """Releve les sommets du trace d'une forme.

    Selon la version de pdfplumber, la cle s'appelle "points" ou "pts".

    Args:
        shape: Forme issue du PDF.

    Returns:
        Sommets, ou liste vide s'ils ne sont pas exposes.
    """
    raw = shape.get("points") or shape.get("pts") or []

    return [
        (float(point[0]), float(point[1]))
        for point in raw
        if isinstance(point, (list, tuple)) and len(point) >= 2
    ]


def _normalized_centroid(shape: dict) -> tuple[float, float] | None:
    """Calcule le centroide des sommets, rapporte a la boite englobante.

    C'est le seul moyen de distinguer deux formes de meme encombrement. Un
    triangle pointant vers le haut concentre ses sommets d'un cote de sa boite,
    celui pointant vers le bas de l'autre: leurs centroides sont separes de 0,5.

    La convention d'axe de pdfplumber n'importe pas, les centroides etant
    toujours compares entre eux.

    Args:
        shape: Forme issue du PDF.

    Returns:
        Couple de coordonnees normalisees entre 0 et 1, ou None si les sommets
        sont absents ou degeneres.
    """
    vertices = _vertices(shape)

    if len(vertices) < 3:
        return None

    xs = [x for x, _ in vertices]
    ys = [y for _, y in vertices]
    span_x = max(xs) - min(xs)
    span_y = max(ys) - min(ys)

    if span_x <= 0 or span_y <= 0:
        return None

    return (
        (sum(xs) / len(xs) - min(xs)) / span_x,
        (sum(ys) / len(ys) - min(ys)) / span_y,
    )


@dataclass(frozen=True, slots=True)
class ShapePrototype:
    """Signature d'une forme, utilisee pour rapprocher grille et legende.

    Attributes:
        object_type: Type d'objet PDF, typiquement "rect" ou "curve".
        width: Largeur en points.
        height: Hauteur en points.
        stroked: La forme possede un contour.
        filled: La forme possede un remplissage.
        fill_color: Couleur de remplissage normalisee.
        stroke_color: Couleur de contour normalisee.
        centroid_x: Centroide horizontal normalise, None si indisponible.
        centroid_y: Centroide vertical normalise, None si indisponible.
    """

    object_type: str
    width: float
    height: float
    stroked: bool
    filled: bool
    fill_color: str
    stroke_color: str
    centroid_x: float | None = None
    centroid_y: float | None = None

    @classmethod
    def from_shape(cls, shape: dict) -> ShapePrototype:
        """Construit la signature d'une forme.

        Args:
            shape: Forme issue du PDF.

        Returns:
            Signature correspondante.
        """
        centroid = _normalized_centroid(shape)

        return cls(
            object_type=str(shape.get("object_type", "rect")),
            width=float(shape["x1"] - shape["x0"]),
            height=float(shape["bottom"] - shape["top"]),
            stroked=bool(shape.get("stroke")),
            filled=bool(shape.get("fill")),
            fill_color=_color_key(shape.get("non_stroking_color")),
            stroke_color=_color_key(shape.get("stroking_color")),
            centroid_x=centroid[0] if centroid else None,
            centroid_y=centroid[1] if centroid else None,
        )

    def distance_to(self, other: ShapePrototype) -> float | None:
        """Mesure l'ecart avec une autre signature.

        Les attributs qualitatifs doivent concorder exactement: un contour ne
        peut pas correspondre a un aplat, deux couleurs de remplissage
        differentes designent deux significations differentes, et deux formes
        d'orientations opposees ne sont pas la meme forme.

        Args:
            other: Signature de reference, typiquement issue de la legende.

        Returns:
            Distance euclidienne sur les dimensions, ou None si les formes sont
            incompatibles.
        """
        if self.object_type != other.object_type:
            return None
        if self.stroked != other.stroked or self.filled != other.filled:
            return None
        if self.filled and not _fills_match(self.fill_color, other.fill_color):
            return None
        if self.stroked and self.stroke_color != other.stroke_color:
            return None
        if not self._orientation_matches(other):
            return None

        return (
            (self.width - other.width) ** 2 + (self.height - other.height) ** 2
        ) ** 0.5

    def _orientation_matches(self, other: ShapePrototype) -> bool:
        """Compare l'orientation de deux formes.

        La comparaison n'a lieu que si les deux signatures disposent d'un
        centroide: lorsque pdfplumber n'expose pas les sommets, seules les
        dimensions departagent les formes.

        Args:
            other: Signature de reference.

        Returns:
            True si les orientations sont compatibles ou indeterminables.
        """
        for mine, theirs in (
            (self.centroid_x, other.centroid_x),
            (self.centroid_y, other.centroid_y),
        ):
            if mine is None or theirs is None:
                continue
            if abs(mine - theirs) > CENTROID_TOLERANCE:
                return False

        return True


def _fills_match(first: str, second: str) -> bool:
    """Compare des remplissages, y compris les motifs PDF anonymes.

    Certains generateurs PDF exposent un motif de remplissage sous un nom de
    ressource (par exemple ``P10``) plutot que sous sa couleur. Le nom change
    d'une cellule a l'autre, mais la geometrie du marqueur reste disponible et
    permet a ``distance_to`` de faire le tri. Les couleurs explicites restent,
    elles, comparees exactement.
    """
    if first == second:
        return True
    return first.startswith("P") and second.startswith("P")


@dataclass(frozen=True, slots=True)
class LegendEntry:
    """Une entree de legende: une forme et sa signification.

    Attributes:
        prototype: Signature de la forme.
        label: Libelle lu a droite de la forme.
        category: Categorie deduite du libelle.
    """

    prototype: ShapePrototype
    label: str
    category: EventCategory


@dataclass(frozen=True, slots=True)
class MonthRegion:
    """Zone occupee par la grille d'un mois.

    Attributes:
        month: Numero du mois.
        year: Annee civile.
        x_center: Abscisse du centre de la colonne.
        half_width: Demi-largeur de la colonne.
        top: Ordonnee superieure de la zone.
        bottom: Ordonnee inferieure de la zone.
    """

    month: int
    year: int
    x_center: float
    half_width: float
    top: float
    bottom: float

    def contains(self, x: float, y: float) -> bool:
        """Verifie si un point appartient a la zone.

        Args:
            x: Abscisse.
            y: Ordonnee.

        Returns:
            True si le point est dans la zone.
        """
        return (
            abs(x - self.x_center) <= self.half_width and self.top <= y <= self.bottom
        )


def _is_candidate_marker(shape: dict) -> bool:
    """Ecarte les formes qui ne peuvent pas entourer un chiffre.

    Elimine les filets de separation, les aplats de fond et les cadres.

    Args:
        shape: Forme issue du PDF.

    Returns:
        True si la forme a la taille d'un marqueur.
    """
    width = shape["x1"] - shape["x0"]
    height = shape["bottom"] - shape["top"]

    regular = (
        MIN_MARKER_SIZE <= width <= MAX_MARKER_SIZE
        and MIN_MARKER_SIZE <= height <= MAX_MARKER_SIZE
    )
    if regular:
        return True

    if (
        shape.get("object_type") == "curve"
        and shape.get("stroke")
        and not shape.get("fill")
        and MIN_MARKER_SIZE / 2 <= width <= MAX_MARKER_SIZE
        and MIN_MARKER_SIZE <= height <= MAX_MARKER_SIZE
    ):
        return True

    fill = shape.get("non_stroking_color")
    return (
        isinstance(fill, str)
        and fill.startswith("P")
        and MIN_MARKER_SIZE <= height <= MAX_MARKER_SIZE
        and MIN_MARKER_SIZE <= width <= MAX_RANGE_MARKER_WIDTH
    )


def _day_words(words: list[dict]) -> list[dict]:
    """Selectionne les mots representant un jour du mois.

    Args:
        words: Mots extraits de la page.

    Returns:
        Mots dont le texte est un entier de 1 a 31.
    """
    selected: list[dict] = []

    for word in words:
        text = word.get("text", "").strip()
        if not text.isdigit():
            continue
        if 1 <= int(text) <= 31:
            selected.append(word)

    return selected


@dataclass(frozen=True, slots=True)
class _HeaderCandidate:
    """En-tete de mois candidat.

    Attributes:
        month: Numero du mois.
        year: Annee civile resolue.
        x_center: Abscisse du centre de l'en-tete.
        top: Ordonnee superieure de l'en-tete.
    """

    month: int
    year: int
    x_center: float
    top: float


def _collect_headers(
    words: list[dict], school_year_start: int
) -> list[_HeaderCandidate]:
    """Releve tous les mots qui pourraient etre un en-tete de mois.

    Args:
        words: Mots extraits de la page.
        school_year_start: Annee scolaire de reference.

    Returns:
        En-tetes candidats, sans filtrage.
    """
    candidates: list[_HeaderCandidate] = []

    for word in words:
        month = MONTH_HEADERS.get(normalize_text(word.get("text", "").strip()))
        if month is None:
            continue

        x_center, _ = _center(word)
        candidates.append(
            _HeaderCandidate(
                month=month,
                year=_year_for_header(words, word, month, school_year_start),
                x_center=x_center,
                top=word["top"],
            )
        )

    return candidates


def _layout(headers: list[_HeaderCandidate], *, generous: bool) -> tuple[float, float]:
    """Deduit la largeur des colonnes et la hauteur des blocs.

    Args:
        headers: En-tetes servant de reference.
        generous: Si True, retient l'ecart maximal entre colonnes plutot que
            l'ecart median. Utilise lors du premier passage, ou des faux
            en-tetes peuvent encore reduire l'ecart median et faire tronquer les
            grilles.

    Returns:
        Couple (demi-largeur de colonne, hauteur de bloc).
    """
    centers = sorted({round(header.x_center, 1) for header in headers})
    tops = sorted({round(header.top, 1) for header in headers})

    # Les dates de la legende peuvent contenir des noms de mois. Les ecarts
    # entre tous les centres melangent alors les trois colonnes de la grille
    # avec ceux de la legende. Les en-tetes alignes sur une meme ligne restent
    # une reference fiable pour mesurer la largeur des colonnes.
    centers_by_top: dict[float, list[float]] = defaultdict(list)
    for header in headers:
        centers_by_top[round(header.top, 1)].append(round(header.x_center, 1))

    column_gaps = [
        second - first
        for row_centers in centers_by_top.values()
        for first, second in zip(
            sorted(set(row_centers)), sorted(set(row_centers))[1:], strict=False
        )
        if second - first > 20
    ]
    if not column_gaps:
        column_gaps = [
            second - first
            for first, second in zip(centers, centers[1:], strict=False)
            if second - first > 20
        ]
    row_gaps = [
        second - first
        for first, second in zip(tops, tops[1:], strict=False)
        if second - first > 20
    ]

    if column_gaps:
        reference = max(column_gaps) if generous else median(column_gaps)
        half_width = reference / 2
    else:
        half_width = DEFAULT_COLUMN_HALF_WIDTH

    block_height = median(row_gaps) - 4.0 if row_gaps else DEFAULT_BLOCK_HEIGHT

    return half_width, block_height


def _region_for(
    header: _HeaderCandidate, half_width: float, block_height: float
) -> MonthRegion:
    """Construit la zone couverte par un en-tete.

    Args:
        header: En-tete de mois.
        half_width: Demi-largeur de colonne.
        block_height: Hauteur du bloc mensuel.

    Returns:
        Zone correspondante.
    """
    return MonthRegion(
        month=header.month,
        year=header.year,
        x_center=header.x_center,
        half_width=half_width,
        top=header.top - 4.0,
        bottom=header.top + block_height,
    )


def _find_month_regions(words: list[dict], school_year_start: int) -> list[MonthRegion]:
    """Localise les grilles mensuelles a partir de leurs en-tetes.

    Un nom de mois cite dans une note de bas de page ou dans un bloc de legende
    ressemble a un en-tete. Les candidats sont donc valides en exigeant qu'ils
    surplombent une vraie grille, c'est-a-dire une vingtaine de numeros de jour.
    Sans ce filtre, ces faux en-tetes reduisent l'ecart median entre colonnes et
    la derniere colonne de chaque grille se retrouve hors des zones.

    La disposition est ensuite recalculee sur les seules zones retenues.

    Args:
        words: Mots extraits de la page.
        school_year_start: Annee scolaire de reference, utilisee si l'annee
            n'accompagne pas l'en-tete.

    Returns:
        Zones mensuelles validees, une par mois.
    """
    headers = _collect_headers(words, school_year_start)

    if len(headers) < 2:
        return []

    days = _day_words(words)

    # Premier passage: bornes volontairement larges, uniquement pour compter les
    # journees couvertes par chaque candidat.
    half_width, block_height = _layout(headers, generous=True)
    scored: list[tuple[int, _HeaderCandidate]] = []

    for header in headers:
        region = _region_for(header, half_width, block_height)
        covered = sum(1 for word in days if region.contains(*_center(word)))
        if covered >= MIN_DAY_WORDS_PER_REGION:
            scored.append((covered, header))

    if len(scored) < 2:
        _LOGGER.debug(
            "%d en-tete(s) candidat(s) mais aucun ne surplombe de grille",
            len(headers),
        )
        return []

    # Un mois nomme a la fois en en-tete et dans une note produit un doublon: on
    # conserve le candidat qui couvre le plus de journees.
    best: dict[tuple[int, int], tuple[int, _HeaderCandidate]] = {}

    for covered, header in scored:
        key = (header.year, header.month)
        if key not in best or covered > best[key][0]:
            best[key] = (covered, header)

    kept = [header for _, header in best.values()]

    if len(kept) < len(headers):
        _LOGGER.debug(
            "%d en-tete(s) candidat(s) reduits a %d grille(s) reelle(s)",
            len(headers),
            len(kept),
        )

    # Second passage: la disposition est mesuree sur les grilles reelles.
    half_width, block_height = _layout(kept, generous=False)

    return [_region_for(header, half_width, block_height) for header in kept]


def _year_for_header(
    words: list[dict], header: dict, month: int, school_year_start: int
) -> int:
    """Determine l'annee civile associee a un en-tete de mois.

    L'annee est cherchee immediatement a droite de l'en-tete. A defaut, elle est
    deduite de l'annee scolaire.

    Args:
        words: Mots extraits de la page.
        header: Mot formant l'en-tete du mois.
        month: Numero du mois.
        school_year_start: Annee scolaire de reference.

    Returns:
        Annee civile.
    """
    _, header_cy = _center(header)

    for word in words:
        text = word.get("text", "").strip()
        if len(text) != 4 or not text.isdigit():
            continue

        _, word_cy = _center(word)
        if abs(word_cy - header_cy) > HEADER_YEAR_LINE_TOLERANCE:
            continue
        if not 0 <= word["x0"] - header["x1"] <= 30:
            continue

        year = int(text)
        if 1990 <= year <= 2100:
            return year

    return resolve_year(month, school_year_start)


def _vertical_overlap(first: dict, second: dict) -> float:
    """Mesure le recouvrement vertical de deux objets positionnes.

    Args:
        first: Premier objet.
        second: Second objet.

    Returns:
        Hauteur commune en points, negative si les objets ne se croisent pas.
    """
    return min(first["bottom"], second["bottom"]) - max(first["top"], second["top"])


def _label_right_of(shape: dict, words: list[dict]) -> str:
    """Lit le texte situe immediatement a droite d'une forme.

    L'appartenance d'un mot a la ligne de la forme est etablie par
    recouvrement vertical, et non par distance entre centres. Un triangle
    pointant vers le haut a sa masse visuelle en bas de sa boite englobante, et
    son libelle est cale sur cette masse: comparer les centres ferait manquer
    l'association.

    La lecture s'arrete au premier ecart horizontal important, afin de ne pas
    happer le contenu d'une colonne voisine. Les nombres en fin de libelle, qui
    correspondent aux totaux imprimes dans la legende, sont retires.

    Args:
        shape: Forme de legende.
        words: Mots extraits de la page.

    Returns:
        Libelle nettoye, possiblement vide.
    """
    overlapping: list[tuple[float, dict]] = []

    for word in words:
        if word["x0"] < shape["x1"] - 1.0:
            continue
        overlap = _vertical_overlap(shape, word)
        if overlap > 0:
            overlapping.append((overlap, word))

    if not overlapping:
        return ""

    # Une forme haute peut croiser deux lignes de texte: seule celle qui la
    # recouvre le plus porte son libelle.
    threshold = max(overlap for overlap, _ in overlapping) * MIN_LABEL_OVERLAP_RATIO
    candidates = [word for overlap, word in overlapping if overlap >= threshold]
    candidates.sort(key=lambda word: word["x0"])

    tokens: list[str] = []
    cursor = shape["x1"]

    for word in candidates:
        if word["x0"] - cursor > LEGEND_TEXT_GAP:
            break
        tokens.append(word.get("text", "").strip())
        cursor = word["x1"]

    while tokens and tokens[-1].isdigit():
        tokens.pop()

    return clean_summary(" ".join(tokens))


def _build_legend(
    shapes: list[dict], words: list[dict], regions: list[MonthRegion]
) -> list[LegendEntry]:
    """Releve les entrees de legende du document.

    Args:
        shapes: Formes candidates.
        words: Mots extraits de la page.
        regions: Zones mensuelles, pour ecarter les formes de grille.

    Returns:
        Entrees de legende exploitables.
    """
    entries: list[LegendEntry] = []
    legend_words = [
        word
        for word in words
        if normalize_text(word.get("text", "").strip()) == "legende"
    ]
    meeting_words = [
        word
        for word in words
        if normalize_text(word.get("text", "").strip()) == "rencontres"
    ]
    legend_left = None
    if legend_words and meeting_words:
        legend_center = sum(_center(word)[0] for word in legend_words) / len(
            legend_words
        )
        meeting_center = sum(_center(word)[0] for word in meeting_words) / len(
            meeting_words
        )
        legend_left = (legend_center + meeting_center) / 2

    for shape in shapes:
        x, y = _center(shape)
        if any(region.contains(x, y) for region in regions):
            continue

        label = _label_right_of(shape, words)
        if not label:
            continue
        if legend_left is not None and x < legend_left:
            is_color_key = (
                y > 700
                and shape.get("fill")
                and isinstance(shape.get("non_stroking_color"), (list, tuple))
            )
            if not is_color_key:
                continue

        entries.append(
            LegendEntry(
                prototype=ShapePrototype.from_shape(shape),
                label=label,
                category=classify(label) or EventCategory.EVENT,
            )
        )

    return entries


def _match_legend(
    prototype: ShapePrototype, legend: list[LegendEntry]
) -> LegendEntry | None:
    """Rattache une forme de grille a l'entree de legende la plus proche.

    Args:
        prototype: Signature de la forme de grille.
        legend: Entrees de legende disponibles.

    Returns:
        Entree correspondante, ou None si aucune n'est assez proche.
    """
    patterned_holidays = [
        entry
        for entry in legend
        if entry.category is EventCategory.HOLIDAY
        and entry.prototype.filled
        and entry.prototype.fill_color.startswith("P")
    ]
    if prototype.filled and prototype.fill_color.startswith("P"):
        relache = next(
            (
                entry
                for entry in patterned_holidays
                if "relache" in normalize_text(entry.label)
            ),
            None,
        )
        if relache is not None:
            return relache

    if prototype.filled and prototype.fill_color.startswith("c"):
        same_color = [
            entry
            for entry in legend
            if entry.prototype.filled
            and entry.prototype.fill_color == prototype.fill_color
        ]
        if same_color:
            return same_color[0]

    if (
        prototype.stroked
        and not prototype.filled
        and prototype.width >= 16
        and prototype.height >= 13.5
    ):
        fin = next(
            (
                entry
                for entry in legend
                if "fin d'etape" in normalize_text(entry.label)
            ),
            None,
        )
        if fin is not None:
            return fin

    best: LegendEntry | None = None
    best_distance = MAX_PROTOTYPE_DISTANCE

    for entry in legend:
        distance = prototype.distance_to(entry.prototype)
        if distance is None or distance > best_distance:
            continue
        best = entry
        best_distance = distance

    if best is None and prototype.filled and prototype.fill_color.startswith("P"):
        if patterned_holidays:
            return patterned_holidays[0]

    return best


def _enclosed_day(shape: dict, days: list[dict]) -> int | None:
    """Determine le jour encadre par une forme.

    Args:
        shape: Forme de grille.
        days: Mots representant des jours.

    Returns:
        Numero du jour, ou None si la forme n'encadre aucun chiffre.
    """
    enclosed = _enclosed_days(shape, days)
    return enclosed[0] if enclosed else None


def _enclosed_days(shape: dict, days: list[dict]) -> list[int]:
    """Retourne tous les jours couverts par un marqueur, y compris une plage."""
    enclosed: list[int] = []
    best_distance = float("inf")
    shape_x, shape_y = _center(shape)

    for word in days:
        word_x, word_y = _center(word)

        if not (
            shape["x0"] - 2.0 <= word_x <= shape["x1"] + 2.0
            and shape["top"] - 2.0 <= word_y <= shape["bottom"] + 2.0
        ):
            continue

        distance = (word_x - shape_x) ** 2 + (word_y - shape_y) ** 2
        if shape["x1"] - shape["x0"] > MAX_MARKER_SIZE:
            enclosed.append(int(word["text"].strip()))
        elif distance < best_distance:
            best_distance = distance
            enclosed = [int(word["text"].strip())]

    return sorted(set(enclosed))


def _merge_consecutive(days: list[date]) -> list[tuple[date, date]]:
    """Regroupe des journees en plages continues.

    Les interruptions constituees uniquement de fins de semaine sont
    enjambees: un conge du vendredi au lundi suivant forme une seule plage,
    conformement a la lecture qu'en fait un parent.

    Args:
        days: Journees marquees, en ordre quelconque.

    Returns:
        Plages (premier jour, dernier jour inclus).
    """
    if not days:
        return []

    ordered = sorted(set(days))
    ranges: list[tuple[date, date]] = []
    start = previous = ordered[0]

    for current in ordered[1:]:
        if _is_bridgeable(previous, current):
            previous = current
            continue
        ranges.append((start, previous))
        start = previous = current

    ranges.append((start, previous))
    return ranges


def _is_bridgeable(previous: date, current: date) -> bool:
    """Verifie si deux journees marquees appartiennent a la meme plage.

    Args:
        previous: Journee precedente.
        current: Journee suivante.

    Returns:
        True si les journees sont consecutives ou separees uniquement par des
        jours de fin de semaine.
    """
    gap = (current - previous).days

    if gap <= 1:
        return True

    return all(
        (previous + timedelta(days=offset)).weekday() in WEEKEND_DAYS
        for offset in range(1, gap)
    )


def extract_events_from_grid(
    words: list[dict],
    shapes: list[dict],
    source_name: str,
    school_year_start: int,
) -> list[SchoolEvent]:
    """Extrait les evenements d'un calendrier presente en grille.

    Args:
        words: Mots extraits de la page, avec leurs boites englobantes.
        shapes: Rectangles, courbes et lignes de la page, avec leurs couleurs.
        source_name: Nom de la source, conserve sur chaque evenement.
        school_year_start: Annee scolaire de reference.

    Returns:
        Evenements dedoublonnes et tries chronologiquement. Liste vide si la
        page n'est pas une grille de calendrier ou si aucune legende
        exploitable n'a ete trouvee.
    """
    regions = _find_month_regions(words, school_year_start)

    if len(regions) < 2:
        _LOGGER.debug(
            "'%s': %d en-tete(s) de mois, pas une grille de calendrier",
            source_name,
            len(regions),
        )
        return []

    candidates = [shape for shape in shapes if _is_candidate_marker(shape)]
    legend = _build_legend(candidates, words, regions)

    if not legend:
        _LOGGER.debug("'%s': aucune legende exploitable", source_name)
        return []

    days = _day_words(words)

    # Regroupement des journees marquees par signification.
    marked: dict[tuple[str, EventCategory], list[date]] = defaultdict(list)

    for shape in candidates:
        x, y = _center(shape)
        region = next((region for region in regions if region.contains(x, y)), None)
        if region is None:
            continue

        entry = _match_legend(ShapePrototype.from_shape(shape), legend)
        if entry is None:
            continue

        enclosed_days = _enclosed_days(shape, days)
        if not enclosed_days:
            continue

        for day in enclosed_days:
            try:
                marked[(entry.label, entry.category)].append(
                    date(region.year, region.month, day)
                )
            except ValueError:
                _LOGGER.debug(
                    "'%s': date impossible %d-%d-%d ignoree",
                    source_name,
                    region.year,
                    region.month,
                    day,
                )

    events: list[SchoolEvent] = []

    for (label, category), day_list in marked.items():
        if len(day_list) > MAX_DAYS_PER_PROTOTYPE:
            _LOGGER.debug(
                "'%s': '%s' marque %d journees, traite comme un ombrage "
                "structurel et ignore",
                source_name,
                label,
                len(day_list),
            )
            continue

        for first_day, last_day in _merge_consecutive(day_list):
            event_summary = label
            if (
                category is EventCategory.HOLIDAY
                and "relache" in normalize_text(label)
            ):
                if (
                    first_day.month == 3
                    and last_day.month == 3
                    and 1 <= first_day.day <= 5
                    and 1 <= last_day.day <= 5
                ):
                    event_summary = "Semaine de relâche"
                else:
                    event_summary = "Congé pour tous"

            events.append(
                SchoolEvent(
                    summary=event_summary,
                    start=first_day,
                    end=last_day + timedelta(days=1),
                    category=category,
                    source=source_name,
                )
            )

    _LOGGER.debug(
        "'%s': %d evenement(s) depuis %d grille(s) mensuelle(s) et %d entree(s) "
        "de legende",
        source_name,
        len(events),
        len(regions),
        len(legend),
    )

    return deduplicate_events(events)
