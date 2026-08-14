import yaml

from app.geo.demo_zones import approximate_outline_geojson
from app.geo.grid import build_grid, geometry_inputs
from app.rules.zone_score import score_cells

RULESET = yaml.safe_load(
    """
zone_score:
  provenance: ai_authored_provisional
  expression: "w_fetch * fetch_norm + w_margin * shore_prox + w_shelter * shelter"
  margin_band_m: 25.0
  max_possible_fetch_m: 400.0
  phase_weights:
    spring_warming:    { w_fetch: -0.40, w_margin: 1.00, w_shelter: 0.60 }
    summer_stagnation: { w_fetch:  0.90, w_margin: 0.20, w_shelter: -0.30 }
  default_phase: summer_stagnation
"""
)

# (row, col, fetch_m, shore_m)
CELLS = [
    (0, 0, 400.0, 60.0),  # fully windward, open water
    (0, 1, 0.0, 2.0),  # sheltered, hard against the bank
    (0, 2, 200.0, 30.0),  # middling
]


def test_scores_are_normalised_to_unit_range():
    scored, phase = score_cells(RULESET, "summer_stagnation", CELLS)
    values = [v for _, _, v in scored]
    assert phase == "summer_stagnation"
    assert min(values) == 0.0
    assert max(values) == 1.0


def test_wind_sign_flips_between_phases():
    """The whole point of the phase table: the windward cell is preferred in
    summer and the sheltered margin is preferred in spring."""
    summer, _ = score_cells(RULESET, "summer_stagnation", CELLS)
    spring, _ = score_cells(RULESET, "spring_warming", CELLS)

    summer_by_cell = {(r, c): v for r, c, v in summer}
    spring_by_cell = {(r, c): v for r, c, v in spring}

    windward, sheltered = (0, 0), (0, 1)
    assert summer_by_cell[windward] > summer_by_cell[sheltered]
    assert spring_by_cell[sheltered] > spring_by_cell[windward]


def test_unknown_phase_falls_back_to_default():
    _, phase = score_cells(RULESET, "not_a_real_phase", CELLS)
    assert phase == "summer_stagnation"


def test_grid_cells_stay_inside_the_outline():
    outline = approximate_outline_geojson(52.5431, 20.6762, 9.0)
    grid = build_grid(outline, 20.0)
    assert grid.cells, "grid should contain water cells"
    # A circle inscribed in its own bounding box covers ~pi/4 of it.
    assert len(grid.cells) < grid.n_rows * grid.n_cols

    inputs = geometry_inputs(outline, grid, 270.0)
    assert len(inputs) == len(grid.cells)
    assert all(fetch >= 0.0 and shore >= 0.0 for _, _, fetch, shore in inputs)
