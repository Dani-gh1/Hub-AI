import threading
import time
import unittest

from hub.server import Overview


class OverviewTests(unittest.TestCase):
    def test_answers_at_once_with_the_last_overview_and_refreshes_in_the_background(self):
        t = [1000.0]
        calls = []
        gate = threading.Event()

        def build():
            calls.append(1)
            if len(calls) > 1:
                gate.wait(2)                       # en langsom bot
            return [len(calls)]

        ov = Overview([], build=build, now=lambda: t[0])
        self.assertEqual(ov.get(), [1])            # første gang venter vi
        t[0] += 5
        self.assertEqual(ov.get(), [1])            # frisk: intet nyt kald
        self.assertEqual(len(calls), 1)
        t[0] += 20
        start = time.time()
        self.assertEqual(ov.get(), [1])            # forældet: svarer straks med det gamle, henter nyt i baggrunden
        self.assertLess(time.time() - start, 0.5)
        self.assertEqual(ov.get(), [1])            # kun én baggrundshentning ad gangen
        gate.set()
        for _ in range(50):
            if ov.rows == [2]:
                break
            time.sleep(0.02)
        self.assertEqual(ov.get(), [2])
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
