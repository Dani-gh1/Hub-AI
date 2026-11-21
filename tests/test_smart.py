import os
import tempfile
import unittest
from pathlib import Path

from hub.server import COST_DEFAULTS, smart_candidates, smart_of, smart_start

H = 3600
T0 = 1_700_000_000


def cand(name, pts, side=0.0, tax=0.0, bot="b"):
    return {"id": f"{bot}:{name}", "name": name, "bot": bot, "bot_name": bot.upper(),
            "curve": [[T0 + h * H, v] for h, v in pts], "side": side, "tax": tax}


class SmartTests(unittest.TestCase):
    def test_follows_the_best_of_the_last_24_hours_and_switches_when_overtaken(self):
        a = cand("A", [(0, 0), (24, 10), (48, 10), (72, 10)])      # stærk første døgn, så flad
        b = cand("B", [(0, 0), (24, 2), (48, 12), (72, 22)])       # overhaler A's seneste 24 timer
        sm = smart_of([a, b], steps=72)
        self.assertEqual(sm["following"], "B")
        self.assertGreaterEqual(sm["switches"], 2)                 # start i én, skift til B
        self.assertEqual(sm["recent"][0]["to"], "B")
        self.assertGreater(sm["return_pct"], 10)                   # fik A's første døgn og en stor del af B's fremgang
        self.assertLessEqual(sm["return_pct"], 22)

    def test_never_looks_ahead(self):
        # B springer først op i sidste skridt: Smart kan ikke have været i B, før springet var sket
        a = cand("A", [(0, 0), (10, 1), (20, 2)])
        b = cand("B", [(0, 0), (10, 0), (19.9, 0), (20, 50)])
        sm = smart_of([a, b], steps=20)
        self.assertEqual(sm["following"], "B")
        self.assertLess(sm["return_pct"], 3)

    def test_each_switch_pays_to_sell_the_old_book_and_buy_the_new(self):
        a = cand("A", [(0, 0), (24, 10), (48, 10)], side=0.5)
        b = cand("B", [(0, 0), (24, 2), (48, 14)], side=0.5)
        free = smart_of([{**a, "side": 0}, {**b, "side": 0}], steps=48)
        paid = smart_of([a, b], steps=48)
        self.assertAlmostEqual(paid["cost_pct"], 0.5 + (paid["switches"] - 1) * 1.0, places=2)
        self.assertAlmostEqual(free["return_pct"] - paid["return_pct"], paid["cost_pct"], places=1)

    def test_tax_only_on_a_gain(self):
        up = smart_of([cand("A", [(0, 0), (10, 10)], tax=50)])
        down = smart_of([cand("A", [(0, 0), (10, -10)], tax=50)])
        self.assertAlmostEqual(up["return_pct"], 5)
        self.assertAlmostEqual(down["return_pct"], -10)

    def test_nothing_to_follow(self):
        self.assertIsNone(smart_of([]))
        self.assertIsNone(smart_of([cand("A", [(0, 0)])]))

    def test_candidates_use_net_curves_and_skip_curves_without_time(self):
        c = {**COST_DEFAULTS, "fee_pct": 0.1, "slip_pct": 0.0, "pos_pct": 10.0}
        sts = [{"key": "a", "name": "A", "trades": 10, "open": 0, "curve": [[T0, 0], [T0 + H, 5]]},
               {"key": "x", "name": "X", "trades": 0, "open": 0, "curve": [[0, 0], [1, 5]]}]
        out = smart_candidates(sts, c, {"key": "bot", "name": "Bot"})
        self.assertEqual([x["name"] for x in out], ["A"])
        self.assertAlmostEqual(out[0]["curve"][-1][1], 5 - 10 * 0.1 * 0.2)       # 10 handler à 0,02 % af kontoen
        self.assertAlmostEqual(out[0]["side"], 0.01)                               # én position à 10 % x 0,1 %
        off = smart_candidates(sts, {**c, "enabled": False}, {"key": "bot", "name": "Bot"})
        self.assertEqual(off[0]["curve"][-1][1], 5)
        self.assertEqual(off[0]["side"], 0)

    def test_starts_from_its_start_time_and_uses_history_only_to_pick_the_leader(self):
        a = cand("A", [(0, 0), (24, 2), (48, 10), (60, 13)])
        b = cand("B", [(0, 0), (24, 2), (48, 3), (60, 4)])
        sm = smart_of([a, b], start=T0 + 48 * H)
        self.assertEqual(sm["since"], T0 + 48 * H)
        self.assertEqual(sm["following"], "A")              # A førte de 24 timer op til start
        self.assertAlmostEqual(sm["return_pct"], 3, places=1)   # kun fremgangen efter start
        self.assertEqual(sm["switches"], 1)

    def test_start_just_now_gives_zero(self):
        sm = smart_of([cand("A", [(0, 0), (10, 5)])], start=T0 + 10 * H)
        self.assertEqual(sm["return_pct"], 0)
        self.assertEqual(sm["following"], "A")

    def test_start_time_is_saved_and_kept(self):
        with tempfile.TemporaryDirectory() as d:
            os.environ["HUB_SMART_FILE"] = str(Path(d) / "smart.json")
            try:
                self.assertEqual(smart_start(now=lambda: 1000.0), 1000.0)
                self.assertEqual(smart_start(now=lambda: 5000.0), 1000.0)
            finally:
                del os.environ["HUB_SMART_FILE"]


if __name__ == "__main__":
    unittest.main()
