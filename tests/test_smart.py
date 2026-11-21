import os
import tempfile
import unittest
from pathlib import Path

from hub.server import COST_DEFAULTS, smart_candidates, smart_of, smart_start

H = 3600
T0 = 1_700_000_000


def cand(name, pts, tax=0.0, bot="b"):
    return {"id": f"{bot}:{name}", "name": name, "bot": bot, "bot_name": bot.upper(),
            "curve": [[T0 + h * H, v] for h, v in pts], "tax": tax, "capital": 10000.0, "currency": "kr."}


class SmartTests(unittest.TestCase):
    def test_follows_the_best_of_the_last_24_hours_and_switches_when_overtaken(self):
        a = cand("A", [(0, 0), (24, 10), (48, 10), (72, 10)])      # stærk første døgn, så flad
        b = cand("B", [(0, 0), (24, 2), (48, 12), (72, 22)])       # overhaler A's seneste 24 timer
        sm = smart_of([a, b], window=24 * H, steps=72)
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

    def test_works_like_a_real_account_with_compounding_and_no_switch_fees(self):
        a = cand("A", [(0, 0), (24, 10), (48, 10)])
        b = cand("B", [(0, 0), (24, 2), (48, 14)])
        sm = smart_of([a, b], steps=48)
        self.assertNotIn("cost_pct", sm)
        self.assertAlmostEqual(sm["value"], sm["capital"] * (1 + sm["return_pct"] / 100), places=0)
        # +10 % og derefter +10 % af en strategi, der står i 110: kontoen vokser 10 % to gange = 21 %
        c = cand("C", [(0, 0), (1, 10), (2, 21)])
        self.assertAlmostEqual(smart_of([c], steps=2)["return_pct"], 21, places=1)

    def test_hops_on_as_soon_as_a_strategy_starts_to_rise(self):
        # alle starter på 0; A stiger jævnt til +10 på 2,5 t og falder så til +5; B stiger stille og roligt til +2
        a = cand("A", [(i / 4, i) for i in range(11)] + [(3, 5)])
        b = cand("B", [(i / 4, i * 0.2) for i in range(11)] + [(3, 2)])
        sm = smart_of([b, a], steps=400)
        first = sm["recent"][-2]                            # første skift efter start: til A, kort efter at A begyndte at stige
        self.assertEqual(first["to"], "A")
        self.assertLessEqual(first["ts"] - T0, 1800)
        self.assertGreater(sm["return_pct"], 3.5)           # fik næsten hele stigningen med: tæt på A's +5 og klart over B's +2
        self.assertLessEqual(sm["return_pct"], 5)

    def test_follows_the_strategy_with_the_highest_total_return_and_switches_when_overtaken(self):
        best = cand("Bedst", [(0, 24.7), (1, 24.7), (2, 24.7), (3, 24.0), (4, 23.0)])
        noisy = cand("Svinger", [(0, 1.0), (1, 5.0), (2, 3.0), (3, 6.0), (4, 5.0)])      # rykker sig meget, men er langt bagud
        sm = smart_of([noisy, best], start=T0)
        self.assertEqual(sm["following"], "Bedst")
        self.assertEqual(sm["switches"], 1)                 # skifter ikke til den, der bare lige har rykket sig
        self.assertEqual(sm["recent"][0]["to"], "Bedst")
        late = cand("Overhaler", [(0, 10.0), (1, 15.0), (2, 25.0), (3, 30.0), (4, 35.0)])
        sm = smart_of([best, late], steps=8)
        self.assertEqual(sm["following"], "Overhaler")      # overhaler på samlet afkast: Smart bytter

    def test_never_below_minus_100(self):
        sm = smart_of([cand("A", [(0, 0), (1, -100), (2, -150)])], steps=2)
        self.assertEqual(sm["return_pct"], -100)

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
        off = smart_candidates(sts, {**c, "enabled": False}, {"key": "bot", "name": "Bot"})
        self.assertEqual(off[0]["curve"][-1][1], 5)

    def test_starts_from_its_start_time_and_uses_history_only_to_pick_the_leader(self):
        a = cand("A", [(0, 0), (24, 2), (48, 10), (60, 13)])
        b = cand("B", [(0, 0), (24, 2), (48, 3), (60, 4)])
        sm = smart_of([a, b], window=24 * H, start=T0 + 48 * H)
        self.assertEqual(sm["since"], T0 + 48 * H)
        self.assertEqual(sm["following"], "A")              # A førte de 24 timer op til start
        self.assertAlmostEqual(sm["return_pct"], (113 / 110 - 1) * 100, places=1)   # kun fremgangen efter start (110 → 113)
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
                Path(os.environ["HUB_SMART_FILE"]).write_text('{"since": 1000.0}')      # gammel beregning: start forfra
                self.assertEqual(smart_start(now=lambda: 7000.0), 7000.0)
            finally:
                del os.environ["HUB_SMART_FILE"]


if __name__ == "__main__":
    unittest.main()
