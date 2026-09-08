"""`ssh-hold skill` writes SKILL.md where Claude Code and Codex look for it."""

from contextlib import contextmanager
from pathlib import Path
import subprocess
import tempfile
import unittest

import context


CLAUDE = ".claude/skills/ssh-hold/SKILL.md"
CODEX = ".codex/skills/ssh-hold/SKILL.md"


@contextmanager
def fake_home(*agents):
    """A throwaway HOME containing only the named agent directories.

    The cache lives in a sibling directory rather than under HOME, so that
    "what did skill install write" stays answerable by walking HOME — the
    standalone build unpacks its embedded copies into the cache on first use.
    """
    with tempfile.TemporaryDirectory(prefix="shs-") as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        (Path(tmp) / "cache").mkdir()
        for agent in agents:
            (home / agent).mkdir(parents=True)
        yield home


class SkillTests(unittest.TestCase):
    def run_skill(self, home, *args, expect_ok=True):
        result = subprocess.run([str(context.BIN), "skill", *args],
                                capture_output=True, text=True, timeout=20,
                                env=context.env(HOME=str(home),
                                                XDG_CACHE_HOME=str(home.parent / "cache")))
        if expect_ok:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    @property
    def shipped(self):
        return context.SKILL.read_text(encoding="utf-8")

    def test_installs_to_detected_agents(self):
        for agents, expected in (((".claude",), [CLAUDE]),
                                 ((".codex",), [CODEX]),
                                 ((".claude", ".codex"), [CLAUDE, CODEX])):
            with self.subTest(agents=agents), fake_home(*agents) as home:
                self.run_skill(home, "install")
                written = sorted(str(p.relative_to(home)) for p in home.rglob("SKILL.md"))
                self.assertEqual(written, sorted(expected))
                for rel in expected:
                    self.assertEqual((home / rel).read_text(encoding="utf-8"), self.shipped)

    def test_frontmatter_survives(self):
        """Both tools key off the YAML frontmatter; a mangled copy would never fire."""
        with fake_home(".claude") as home:
            self.run_skill(home, "install")
            text = (home / CLAUDE).read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        head = text.split("---", 2)[1]
        self.assertIn("name: ssh-hold", head)
        self.assertIn("description:", head)
        self.assertIn("ssh-hold paste", text)
        self.assertNotIn("sshpass", text)

    def test_explicit_flag_ignores_detection(self):
        with fake_home() as home:  # 两个 agent 目录都不存在
            self.run_skill(home, "install", "--codex")
            self.assertTrue((home / CODEX).exists())
            self.assertFalse((home / CLAUDE).exists())

    def test_custom_dir(self):
        with fake_home(".claude") as home:
            target = home / "elsewhere"
            self.run_skill(home, "install", "--dir", str(target))
            self.assertTrue((target / "ssh-hold/SKILL.md").exists())
            # --dir 算显式指定，就不该再自动往 ~/.claude 里塞一份
            self.assertFalse((home / CLAUDE).exists())

    def test_no_agent_found_is_an_error(self):
        with fake_home() as home:
            result = self.run_skill(home, "install", expect_ok=False)
            self.assertIn("没找到", result.stderr)

    def test_reinstall_is_quiet_and_edits_are_kept(self):
        with fake_home(".claude") as home:
            installed = home / CLAUDE
            self.run_skill(home, "install")

            again = self.run_skill(home, "install")
            self.assertIn("已是最新", again.stdout)
            self.assertEqual(list(installed.parent.glob("*.bak.*")), [])

            installed.write_text("我自己改过的内容\n", encoding="utf-8")
            third = self.run_skill(home, "install")
            self.assertIn("已备份", third.stdout)
            backups = list(installed.parent.glob("SKILL.md.bak.*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "我自己改过的内容\n")
            self.assertEqual(installed.read_text(encoding="utf-8"), self.shipped)

    def test_path_reports_without_writing(self):
        with fake_home(".claude", ".codex") as home:
            result = self.run_skill(home, "path")
            self.assertEqual(result.stdout.split(), [str(home / CLAUDE), str(home / CODEX)])
            self.assertEqual(list(home.rglob("SKILL.md")), [])

    def test_show_prints_the_file(self):
        with fake_home() as home:
            result = self.run_skill(home, "show")
        self.assertEqual(result.stdout, self.shipped)

    def test_rejects_unknown_subcommand(self):
        with fake_home(".claude") as home:
            result = self.run_skill(home, "instal", expect_ok=False)
            self.assertIn("未知的 skill 子命令", result.stderr)
            self.assertEqual(list(home.rglob("SKILL.md")), [])


if __name__ == "__main__":
    unittest.main()
