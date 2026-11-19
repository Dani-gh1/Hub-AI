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


if __name__ == "__main__":
    unittest.main()
