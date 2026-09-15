"""---- EVERY SECTOR REACHES THE RANKER. 15 September 2026. ----

RAYMOND and FIRSTCRY read "sector unknown" on the board with their
SECTOR filled in the master. core/ranker.sector_moves() read only the
top-10 gaining and top-10 losing sectors, so a sector in the middle of
the table had no move, `excess` was None, and the "beating its sector"
gate was silently skipped for every stock in it.
"""

from core.ranker import sector_moves


def _table(n_sectors=29):
    rows = [{"sector": f"S{i}", "avg_change_pct": round(1.5 - i * 0.1, 2),
             "symbol_count": 5} for i in range(n_sectors)]
    gainers = [r for r in rows if r["avg_change_pct"] >= 0][:10]
    losers = sorted([r for r in rows if r["avg_change_pct"] < 0],
                    key=lambda r: r["avg_change_pct"])[:10]
    return rows, {"sector_gainers": gainers, "sector_losers": losers,
                  "sectors_all": rows}


def test_a_mid_table_sector_has_a_move():
    rows, table = _table()
    shown = {r["sector"] for r in table["sector_gainers"] + table["sector_losers"]}
    middle = [r["sector"] for r in rows if r["sector"] not in shown]
    assert middle, "the fixture must have sectors off both top-10 lists"
    moves = sector_moves(table)
    for name in middle:
        assert name in moves, f"{name} is off the screen lists and got no move"


def test_without_the_full_list_the_old_lists_still_work():
    _, table = _table()
    del table["sectors_all"]
    assert sector_moves(table)["S0"] == 1.5


def test_the_payload_carries_every_sector():
    import pathlib
    src = pathlib.Path("dashboard/state.py").read_text(encoding="utf-8")
    assert '"sectors_all": [dict(r) for r in sector_rows]' in src
    assert '"sectors_all": sector.get("sectors_all") or []' in src
