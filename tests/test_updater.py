import subprocess
import tempfile
import unittest
from pathlib import Path

from hub import updater


def git(*a, cwd=None):
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True)


class UpdaterTests(unittest.TestCase):
    def test_pulls_new_commits_and_leaves_untracked_data_alone(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            git("init", "-q", "--bare", "-b", "main", str(d / "remote.git"))
            git("clone", "-q", str(d / "remote.git"), str(d / "bot"))
            git("clone", "-q", str(d / "remote.git"), str(d / "work"))
            for repo in ("bot", "work"):
                git("config", "user.email", "t@t", cwd=d / repo)
                git("config", "user.name", "t", cwd=d / repo)
            (d / "work" / "a.txt").write_text("1")
            git("add", "-A", cwd=d / "work"); git("commit", "-qm", "ét", cwd=d / "work"); git("branch", "-M", "main", cwd=d / "work"); git("push", "-q", "-u", "origin", "main", cwd=d / "work")
            git("pull", "-q", "origin", "main", cwd=d / "bot")
            (d / "bot" / "var").mkdir()
            (d / "bot" / "var" / "state.json").write_text("RIGTIG BOG")          # botternes data er ikke i git
            self.assertEqual(updater.update_dir(d / "bot")[0], "ens")
            (d / "work" / "a.txt").write_text("2")
            git("commit", "-qam", "to", cwd=d / "work"); git("push", "-q", cwd=d / "work")
            status, text = updater.update_dir(d / "bot")
            self.assertEqual(status, "ny")
            self.assertIn("→", text)
            self.assertEqual((d / "bot" / "a.txt").read_text(), "2")
            self.assertEqual((d / "bot" / "var" / "state.json").read_text(), "RIGTIG BOG")

    def test_a_directory_without_git_is_reported_not_crashed_on(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(updater.update_dir(Path(d))[0], "fejl")

    def test_update_bots_skips_disabled_external_and_missing_ones(self):
        with tempfile.TemporaryDirectory() as d:
            msgs = []
            bots = [{"key": "a", "name": "A", "repo": "x/a", "disabled": True}, {"key": "b", "name": "B", "repo": "x/b", "external": True},
                    {"key": "c", "name": "C", "repo": "x/c"}, {"key": "d", "name": "D"}]
            self.assertEqual(updater.update_bots(bots, lambda b: Path(d) / "findes-ikke", say=msgs.append), {})
            self.assertEqual(msgs, [])

    def _repo(self, d):
        git("init", "-q", "--bare", "-b", "main", str(d / "remote.git"))
        for n in ("bot", "work"):
            git("clone", "-q", str(d / "remote.git"), str(d / n))
            git("config", "user.email", "t@t", cwd=d / n); git("config", "user.name", "t", cwd=d / n)
        (d / "work" / "config.py").write_text("EPOCH = 1\nX = 1\n")
        git("add", "-A", cwd=d / "work"); git("commit", "-qm", "ét", cwd=d / "work"); git("branch", "-M", "main", cwd=d / "work"); git("push", "-q", "-u", "origin", "main", cwd=d / "work")
        git("pull", "-q", "origin", "main", cwd=d / "bot")

    def test_an_update_that_would_reset_the_statistics_is_held_back(self):
        import os
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); self._repo(d)
            (d / "work" / "config.py").write_text("EPOCH = 2\nX = 1\n")
            git("commit", "-qam", "nulstil", cwd=d / "work"); git("push", "-q", cwd=d / "work")
            status, text = updater.update_dir(d / "bot")
            self.assertEqual(status, "holdt"); self.assertIn("EPOCH = 2", text)
            self.assertIn("EPOCH = 1", (d / "bot" / "config.py").read_text())                 # intet hentet
            os.environ["HUB_ALLOW_RESET"] = "1"
            try:
                self.assertEqual(updater.update_dir(d / "bot")[0], "ny")                      # kun når du selv vil det
            finally:
                del os.environ["HUB_ALLOW_RESET"]

    def test_normal_updates_and_epoch_in_tests_or_new_code_still_go_through(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); self._repo(d)
            (d / "work" / "config.py").write_text("EPOCH = 1\nX = 2\nprint(epoch)\nepoch = store.get()\n")
            (d / "work" / "tests").mkdir(); (d / "work" / "tests" / "t.py").write_text("EPOCH = 9\n")
            git("add", "-A", cwd=d / "work"); git("commit", "-qm", "ok", cwd=d / "work"); git("push", "-q", cwd=d / "work")
            self.assertEqual(updater.update_dir(d / "bot")[0], "ny")

    def test_backup_saves_ignored_data_and_prunes_old_copies(self):
        from hub import backup
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); self._repo(d)
            (d / "bot" / ".gitignore").write_text("var/\nstate.json\n__pycache__/\n")
            (d / "bot" / "var").mkdir(); (d / "bot" / "var" / "db").write_text("HANDLER"); (d / "bot" / "state.json").write_text("BOG")
            (d / "bot" / "__pycache__").mkdir(); (d / "bot" / "__pycache__" / "x.pyc").write_text("x")
            root = d / "root"; root.mkdir()
            out = backup.backup_bots({"bot": d / "bot"}, root, say=lambda *_: None, force=True)
            import tarfile
            names = sorted(tarfile.open(out / "bot.tar.gz").getnames())
            self.assertEqual(names, ["state.json", "var/db"])
            self.assertIsNone(backup.backup_bots({"bot": d / "bot"}, root, say=lambda *_: None))   # højst hver 6. time
            for i in range(20):
                (root / "backups" / f"2020010{i % 10}-0000{i:02d}").mkdir(exist_ok=True)
            backup.prune(root / "backups")
            self.assertEqual(len(list((root / "backups").iterdir())), backup.KEEP)


if __name__ == "__main__":
    unittest.main()
