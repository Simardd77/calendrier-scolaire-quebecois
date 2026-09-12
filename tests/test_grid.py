from custom_components.calendrier_scolaire_quebecois.parsers.grid import (
    ShapePrototype,
    _HeaderCandidate,
    _layout,
)


def test_layout_ignore_les_mois_cites_dans_la_legende():
    headers = [
        _HeaderCandidate(month, 2026, center, 150.0)
        for month, center in ((7, 142.0), (8, 310.0), (9, 479.0))
    ]
    headers.extend(
        [
            _HeaderCandidate(8, 2026, 170.0, 640.0),
            _HeaderCandidate(9, 2026, 268.0, 640.0),
        ]
    )

    half_width, _ = _layout(headers, generous=True)

    assert half_width == 84.0


def test_shape_prototype_accepte_deux_motifs_pdf():
    def shape(fill_color: str) -> dict:
        return {
            "object_type": "curve",
            "x0": 0.0,
            "x1": 14.6,
            "top": 0.0,
            "bottom": 12.8,
            "stroke": False,
            "fill": True,
            "non_stroking_color": fill_color,
            "stroking_color": 0,
        }

    assert ShapePrototype.from_shape(shape("P10")).distance_to(
        ShapePrototype.from_shape(shape("P26"))
    ) == 0.0
    assert ShapePrototype.from_shape(shape("0.918")).distance_to(
        ShapePrototype.from_shape(shape("1.0"))
    ) is None