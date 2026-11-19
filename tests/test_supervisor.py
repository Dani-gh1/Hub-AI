import tempfile
import unittest
from pathlib import Path

from hub import supervisor as sv
from hub.supervisor import Supervisor, Unit


class FakeProc:
    def __init__(self):
        self.code = None
        self.terminated = self.killed = False

    def poll(self):
        return self.code

    def terminate(self):
        self.terminated, self.code = True, -15

    def kill(self):
        self.killed, self.code = True, -9

    def wait(self, timeout=None):
        return self.code


class Rig:
    def __init__(self, port=8800, busy=False):
        self.t, self.procs, self.msgs, self.open, self.busy = 1000.0, [], [], False, busy
        self.dir = tempfile.TemporaryDirectory()
        self.unit = Unit("a", "Bot A", ["x"], Path(self.dir.name), port)
        self.sup = Supervisor([self.unit], Path(self.dir.name) / "logs", lambda p: self.open or self.busy,
                              popen=self.popen, now=lambda: self.t, say=self.msgs.append)

    def popen(self, cmd, **kw):
        p = FakeProc()
        self.procs.append(p)
        return p

    def advance(self, s):
        self.t += s
        self.sup.tick()


class SupervisorTests(unittest.TestCase):
    def test_starts_and_restarts_a_crashed_bot_with_growing_pauses(self):
        r = Rig()
        r.sup.tick()
        self.assertEqual(len(r.procs), 1)
        r.open = True
        r.advance(10)
        r.procs[-1].code = 1                       # crash: the dashboard port closes with it
        r.open = False
        r.advance(1)
        self.assertIsNone(r.unit.proc)
        r.advance(3)                               # still inside the 5 s pause
        self.assertEqual(len(r.procs), 1)
        r.advance(10)                              # pause over: started again
        self.assertEqual(len(r.procs), 2)
        r.open = True
        r.procs[-1].code = 1                       # crashes again right away: the pause doubles
        r.open = False
        r.advance(1)
        self.assertEqual(r.unit.backoff, 20.0)
        for _ in range(10):                        # many crashes: the pause never exceeds 5 minutes
            r.advance(400)
            if r.unit.proc:
                r.procs[-1].code = 1
                r.advance(1)
        self.assertLessEqual(r.unit.backoff, sv.BACKOFF_MAX)
        r.dir.cleanup()

    def test_a_stable_run_resets_the_pause(self):
        r = Rig()
        r.sup.tick()
        r.open = True
        r.unit.backoff = 160.0
        r.advance(sv.STABLE_AFTER + 5)
        r.procs[-1].code = 1
        r.open = False
        r.advance(1)
        self.assertEqual(r.unit.next_start - r.t, sv.BACKOFF_START)      # a stable run: back to the short pause
        r.dir.cleanup()

    def test_a_hung_bot_is_killed_and_restarted(self):
        r = Rig()
        r.sup.tick()
        r.open = True
        r.advance(20)                              # answering: fine
        r.open = False                             # the process lives but the dashboard is silent
        r.advance(sv.HANG_AFTER - 30)
        self.assertFalse(r.procs[-1].terminated)
        r.advance(60)
        self.assertTrue(r.procs[0].terminated)
        r.advance(sv.BACKOFF_START + 1)
        self.assertEqual(len(r.procs), 2)
        r.dir.cleanup()

    def test_waits_for_an_old_process_to_release_the_port(self):
        r = Rig(busy=True)
        r.sup.tick()
        r.advance(30)
        self.assertEqual(len(r.procs), 0)          # port still taken: wait, do not fail
        r.busy = False
        r.advance(4)
        self.assertEqual(len(r.procs), 1)
        r.dir.cleanup()

    def test_gives_up_waiting_after_a_while_and_starts_anyway(self):
        r = Rig(busy=True)
        r.sup.tick()
        for _ in range(60):
            r.advance(3)
        self.assertEqual(len(r.procs), 1)
        r.dir.cleanup()

    def test_a_bot_that_runs_but_stopped_scanning_is_restarted(self):
        r = Rig()
        r.unit.health = lambda: self.age
        self.age = 60.0
        r.sup.tick()
        r.open = True
        r.advance(sv.GRACE + 5)                    # en nystartet bot får lov at komme i gang
        self.assertFalse(r.procs[0].terminated)    # scanner fint
        self.age = sv.STALL_AFTER + 60             # … men står nu stille
        r.advance(sv.HEALTH_EVERY + 1)
        self.assertTrue(r.procs[0].terminated)
        r.open = False
        r.advance(sv.BACKOFF_START + 1)
        self.assertEqual(len(r.procs), 2)
        r.dir.cleanup()

    def test_unknown_scan_time_never_triggers_a_restart(self):
        r = Rig()
        r.unit.health = lambda: None               # fx børsen er spærret: genstart hjælper ikke
        r.sup.tick()
        r.open = True
        r.advance(sv.GRACE + 5)
        r.advance(sv.STALL_AFTER * 2)
        self.assertFalse(r.procs[0].terminated)
        r.dir.cleanup()

    def test_a_failing_health_check_does_not_kill_the_supervisor(self):
        r = Rig()
        r.unit.health = lambda: 1 / 0
        r.sup.tick()
        r.open = True
        r.advance(sv.GRACE + 5)
        r.advance(sv.HEALTH_EVERY + 1)
        self.assertFalse(r.procs[0].terminated)
        r.dir.cleanup()

    def test_units_without_a_port_are_not_watched_for_hanging(self):
        r = Rig(port=None)
        r.sup.tick()
        r.advance(sv.HANG_AFTER * 3)
        self.assertFalse(r.procs[0].terminated)
        r.dir.cleanup()

    def test_shutdown_terminates_everything_and_logs_are_written(self):
        r = Rig()
        r.sup.tick()
        r.sup.shutdown(wait=1)
        self.assertTrue(r.procs[0].terminated)
        self.assertTrue((Path(r.dir.name) / "logs" / "a.log").read_text().startswith("\n--- start"))
        r.dir.cleanup()

    def test_a_bot_that_keeps_crashing_gets_healed_and_the_counter_resets_when_it_runs_stable(self):
        r = Rig(); calls = []
        r.unit.heal = lambda n: calls.append(n) or "rettet"
        r.sup.tick()
        for _ in range(6):
            r.procs[-1].code = 1
            r.sup.tick()                       # opdager nedbruddet
            r.advance(400)                     # pause, og så startes den igen
        self.assertEqual(calls, [1, 2])        # efter 3. og 6. hurtige nedbrud
        self.assertTrue(any("🔧" in m for m in r.msgs))
        r.open = True
        r.advance(700)                         # kører stabilt i 10+ min
        r.procs[-1].code = 1; r.sup.tick()
        self.assertEqual((r.unit.fast_fails, r.unit.heals), (0, 0))

    def test_on_stable_is_called_once_after_ten_minutes(self):
        r = Rig(); n = []
        r.unit.on_stable = lambda: n.append(1)
        r.sup.tick(); r.open = True
        r.advance(300); self.assertEqual(n, [])
        r.advance(400); r.advance(60); self.assertEqual(n, [1])


if __name__ == "__main__":
    unittest.main()
