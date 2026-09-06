"""Inspection ciblee des marqueurs d'un calendrier scolaire en grille.

Ignore les fonds de cellule pour ne garder que les formes porteuses de sens,
puis valide la correspondance forme -> (mois, jour).

Usage:
    python3 inspect2.py [chemin.pdf]
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

DEFAULT_PDF = Path(__file__).resolve().parent / "cssp-2026-2027.pdf"

MONTH_NUMBERS = {
    "JANVIER": 1,
    "FEVRIER": 2,
    "FÉVRIER": 2,
    "MARS": 3,
    "AVRIL": 4,
    "MAI": 5,
    "JUIN": 6,
    "JUILLET": 7,
    "AOUT": 8,
    "AOÛT": 8,
    "SEPTEMBRE": 9,
    "OCTOBRE": 10,
    "NOVEMBRE": 11,
    "DECEMBRE": 12,
    "DÉCEMBRE": 12,
}

# Hauteur approximative d'un bloc mensuel, deduite de l'ecart entre rangees
# d'en-tetes (106 -> 240 -> 374 -> 508).
BLOCK_HEIGHT = 130.0


def fmt_color(value: object) -> str:
    """Formate une couleur pdfplumber de maniere compacte."""
    if value is None:
        return "none"
    if isinstance(value, (int, float)):
        return f"g{float(value):.3f}"
    if isinstance(value, (list, tuple)):
        return "(" + ",".join(f"{float(c):.2f}" for c in value) + ")"
    return str(value)


def center(obj: dict) -> tuple[float, float]:
    """Retourne le centre d'un objet pdfplumber."""
    return ((obj["x0"] + obj["x1"]) / 2, (obj["top"] + obj["bottom"]) / 2)


def encloses(shape: dict, word: dict, tolerance: float = 2.0) -> bool:
    """Verifie si une forme encadre le centre d'un mot."""
    cx, cy = center(word)
    return (
        shape["x0"] - tolerance <= cx <= shape["x1"] + tolerance
        and shape["top"] - tolerance <= cy <= shape["bottom"] + tolerance
    )


def is_background(shape: dict) -> bool:
    """Detecte un fond de cellule plutot qu'un marqueur.

    Un fond est rempli, sans contour, et large: il couvre la cellule entiere ou
    une bande complete.
    """
    if shape.get("stroke"):
        return False
    if not shape.get("fill"):
        return False
    return shape["width"] > 9.0 and shape.get("linewidth", 0) == 0


def main() -> int:
    """Point d'entree."""
    try:
        import pdfplumber
    except ImportError:
        print("pdfplumber n'est pas installe.")
        return 1

    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PDF

    if not path.is_file():
        print(f"PDF introuvable : {path}. Passe le chemin en argument.")
        return 1

    with pdfplumber.open(path) as pdf:
        page = pdf.pages[0]
        words = page.extract_words()
        numeric = [w for w in words if w["text"].strip().isdigit()]

        # --- Regions mensuelles ---------------------------------------------
        headers = []
        for word in words:
            key = word["text"].strip().upper()
            if key in MONTH_NUMBERS:
                headers.append((MONTH_NUMBERS[key], key, word))

        columns = sorted({round(w["x0"] / 190) for _, _, w in headers})

        def region_of(shape: dict) -> tuple[int, str] | None:
            cx, cy = center(shape)
            for month, name, word in headers:
                wx, wy = center(word)
                column_ok = abs(wx - cx) < 95
                row_ok = word["top"] - 4 <= cy <= word["top"] + BLOCK_HEIGHT
                if column_ok and row_ok:
                    return month, name
            return None

        print("=" * 78)
        print("A. COURBES (cercles et losanges attendus)")
        print("=" * 78)
        print(
            f"  {'#':>3} {'larg':>5} {'haut':>5} {'ratio':>5} {'pts':>3} "
            f"{'strk':>4} {'fill':>4} {'lw':>4} {'jour':>4} {'mois':>10}  "
            f"contour / remplissage"
        )
        for index, curve in enumerate(page.curves):
            inside = [w["text"] for w in numeric if encloses(curve, w)]
            region = region_of(curve)
            ratio = curve["width"] / curve["height"] if curve["height"] else 0
            print(
                f"  {index:>3} {curve['width']:>5.1f} {curve['height']:>5.1f} "
                f"{ratio:>5.2f} {len(curve.get('points', [])):>3} "
                f"{str(curve['stroke'])[0]:>4} {str(curve['fill'])[0]:>4} "
                f"{curve.get('linewidth', 0):>4.1f} "
                f"{(inside[0] if inside else '-'):>4} "
                f"{(region[1] if region else '-'):>10}  "
                f"{fmt_color(curve.get('stroking_color'))} / "
                f"{fmt_color(curve.get('non_stroking_color'))}"
            )

        print()
        print("=" * 78)
        print("B. RECTANGLES AVEC CONTOUR (carres attendus)")
        print("=" * 78)
        stroked = [r for r in page.rects if r.get("stroke")]
        print(f"  {len(stroked)} rectangle(s) avec contour")
        print(
            f"  {'#':>3} {'larg':>5} {'haut':>5} {'lw':>4} {'fill':>4} "
            f"{'jour':>4} {'mois':>10}  contour / remplissage"
        )
        for index, rect in enumerate(stroked):
            inside = [w["text"] for w in numeric if encloses(rect, w)]
            region = region_of(rect)
            print(
                f"  {index:>3} {rect['width']:>5.1f} {rect['height']:>5.1f} "
                f"{rect.get('linewidth', 0):>4.1f} {str(rect['fill'])[0]:>4} "
                f"{(inside[0] if inside else '-'):>4} "
                f"{(region[1] if region else '-'):>10}  "
                f"{fmt_color(rect.get('stroking_color'))} / "
                f"{fmt_color(rect.get('non_stroking_color'))}"
            )

        print()
        print("=" * 78)
        print("C. COULEURS DE REMPLISSAGE DISTINCTES (tous rects)")
        print("=" * 78)
        fills: Counter[str] = Counter()
        for rect in page.rects:
            fills[fmt_color(rect.get("non_stroking_color"))] += 1
        for color, count in fills.most_common():
            print(f"  {count:>4}x  {color}")
        print()
        print("  Un fond non blanc et non gris signalerait un surlignage colore.")

        print()
        print("=" * 78)
        print("D. MARQUEURS NON RECONNUS COMME FONDS")
        print("=" * 78)
        markers = [
            ("rect", r) for r in page.rects if not is_background(r)
        ] + [("curve", c) for c in page.curves if not is_background(c)]
        print(f"  {len(markers)} marqueur(s) potentiel(s)")

        by_month: dict[str, list[str]] = {}
        legend: list[str] = []

        for kind, shape in markers:
            inside = [w["text"] for w in numeric if encloses(shape, w)]
            region = region_of(shape)
            label = (
                f"{kind}:{shape['width']:.0f}x{shape['height']:.0f}"
                f":{len(shape.get('points', [])) if kind == 'curve' else 0}pts"
                f":lw{shape.get('linewidth', 0):.1f}"
            )
            if region is None:
                legend.append(f"{label} y={shape['top']:.0f} jour={inside}")
                continue
            by_month.setdefault(region[1], []).append(
                f"{inside[0] if inside else '?'}({label})"
            )

        for month_name in [name for _, name, _ in headers]:
            entries = by_month.get(month_name, [])
            print(f"\n  {month_name} : {len(entries)} marqueur(s)")
            for entry in entries:
                print(f"      {entry}")

        print(f"\n  HORS GRILLE (legende ou cadres) : {len(legend)}")
        for entry in legend[:25]:
            print(f"      {entry}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
