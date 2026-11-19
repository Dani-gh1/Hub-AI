import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from hub import heal, updater
from hub.backup import backup_bots


def git(*a, cwd):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class HealTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); d = Path(self.tmp.name)
        git("init", "-q", "--bare", "-b", "main", str(d / "remote.git"), cwd=d)
        for n in ("bot", "work"):
            git("clone", "-q", str(d / "remote.git"), str(d / n), cwd=d)
            git("config", "user.email", "t@t", cwd=d / n); git("config", "user.name", "t", cwd=d / n)
        (d / "work" / "bot.py").write_text("print('ok')\n"); (d / "work" / ".gitignore").write_text("var/\n")
        git("add", "-A", cwd=d / "work"); git("commit", "-qm", "god", cwd=d / "work"); git("branch", "-M", "main", cwd=d / "work"); git("push", "-q", "-u", "origin", "main", cwd=d / "work")
        git("pull", "-q", "origin", "main", cwd=d / "bot")
        self.d, self.bot, self.work, self.log = d, d / "bot", d / "work", d / "bot.log"
        self.root = d / "root"; self.root.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_corrupt_data_is_restored_from_the_latest_backup(self):
        (self.bot / "var").mkdir(); (self.bot / "var" / "db").write_text("GOD BOG"); (self.bot / "var" / "db-wal").write_text("gammel wal")
        backup_bots({"bot": self.bot}, self.root, say=lambda *_: None, force=True)
        (self.bot / "var" / "db").write_text("ØDELAGT"); (self.bot / "var" / "db-wal").write_text("rod")
        self.log.write_text("sqlite3.DatabaseError: database disk image is malformed\n")
        msg = heal.heal("bot", self.bot, self.root, self.log, 1)
        self.assertIn("gendannet", msg)
        self.assertEqual((self.bot / "var" / "db").read_text(), "GOD BOG")

    def test_a_bad_new_version_is_rolled_back_and_not_pulled_again(self):
        heal.mark_good(self.bot)
        good = git("rev-parse", "HEAD", cwd=self.bot)
        (self.work / "bot.py").write_text("raise SystemExit(1)\n")
        git("commit", "-qam", "dårlig", cwd=self.work); git("push", "-q", cwd=self.work)
        self.assertEqual(updater.update_dir(self.bot)[0], "ny")                 # den dårlige version er hentet
        self.log.write_text("Traceback ... SystemExit: 1\n")
        msg = heal.heal("bot", self.bot, self.root, self.log, 2)
        self.assertIn("gik tilbage", msg)
        self.assertEqual(git("rev-parse", "HEAD", cwd=self.bot), good)
        self.assertEqual(updater.update_dir(self.bot)[0], "holdt")             # hentes ikke igen
        (self.work / "bot.py").write_text("print('rettet')\n")
        git("commit", "-qam", "rettet", cwd=self.work); git("push", "-q", cwd=self.work)
        self.assertEqual(updater.update_dir(self.bot)[0], "ny")                 # men en ny version hentes
        self.assertIn("rettet", (self.bot / "bot.py").read_text())

    def test_first_attempt_pulls_a_published_fix(self):
        (self.work / "bot.py").write_text("print('fix')\n")
        git("commit", "-qam", "fix", cwd=self.work); git("push", "-q", cwd=self.work)
        self.assertIn("hentede", heal.heal("bot", self.bot, self.root, self.log, 1))

    def test_nothing_to_fix_is_reported_honestly(self):
        self.assertIn("ingen automatisk rettelse", heal.heal("bot", self.bot, self.root, self.log, 2))


if __name__ == "__main__":
    unittest.main()
