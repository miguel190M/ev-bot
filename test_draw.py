"""Soccer draws lose team bets (3-way h2h); other sports still void. Run: python test_draw.py"""
from src import bets


def bet(sport, outcome, **kw):
    b = {"sport_key": sport, "market_key": "h2h", "home_team": "Home", "away_team": "Away", "outcome": outcome,
         "price": 2.9, "stake": 10.0, "commission": 0.0, "status": "open", "profit": None}
    b.update(kw)
    return b


def test_soccer_draw_loses_team_bets_and_wins_draw_bets():
    for out in ("Home", "Away"):
        b = bet("soccer_australia_aleague", out)
        bets._resolve_h2h(b, 1, 1)
        assert b["status"] == "lost" and b["profit"] == -10.0
    d = bet("soccer_epl", "Draw", price=3.4)
    bets._resolve_h2h(d, 0, 0)
    assert d["status"] == "won" and d["profit"] == 24.0
    w = bet("soccer_epl", "Home")
    bets._resolve_h2h(w, 2, 1)
    assert w["status"] == "won"


def test_two_way_sports_still_void_on_a_tie():
    for sport in ("basketball_nba", "tennis_atp_x", "rugbyleague_nrl"):
        b = bet(sport, "Home")
        bets._resolve_h2h(b, 20, 20)
        assert b["status"] == "void" and b["profit"] == 0.0


def test_repair_old_draw_voids_once():
    L = {"c750": bet("soccer_australia_aleague", "Away", status="void", profit=0.0, settled_by=None),
         "man": bet("soccer_epl", "Home", status="void", profit=0.0, settled_by="manual"),   # user voided: keep
         "draw": bet("soccer_epl", "Draw", status="void", profit=0.0),                      # not a team bet: keep
         "ten": bet("tennis_atp_x", "Home", status="void", profit=0.0),
         "tot": bet("soccer_epl", "Over 2.5", status="void", profit=0.0, market_key="totals")}
    assert bets.fix_soccer_draw_voids(L) == ["c750"]
    assert L["c750"]["status"] == "lost" and L["c750"]["profit"] == -10.0
    assert all(L[k]["status"] == "void" for k in ("man", "draw", "ten", "tot"))
    assert bets.fix_soccer_draw_voids(L) == []                                              # idempotent


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
    print("all passed")
