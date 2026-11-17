"""Channel bookkeeping and file transfer, with ssh and scp replaced by stand-ins.

No network and no real server: a fake `ssh` answers every call with success, so
any recorded channel looks alive, and a fake `scp` writes down the arguments it
was handed. What is under test is which channel gets picked and what scp is
asked to do — not scp itself.
"""

from contextlib import contextmanager
from pathlib import Path
import subprocess
import tempfile
import unittest

import context


META = "TARGET=ubuntu@10.0.0.{n}\nPORT=22{n}{n}\nSTARTED=now\nAUTH=key\nINSECURE=0\n"
ALIVE = "#!/bin/sh\nexit 0\n"
RECORD = '#!/bin/sh\nfor arg in "$@"; do printf \'%s\\n\' "$arg"; done >"$SCP_LOG"\n'


@contextmanager
def sandbox(*channels):
    """A channel directory holding the named channels, plus the stand-in tools."""
    with tempfile.TemporaryDirectory(prefix="shc-") as tmp:
        root = Path(tmp)
        (root / "bin").mkdir()
        for tool, body in (("ssh", ALIVE), ("scp", RECORD)):
            (root / "bin" / tool).write_text(body, encoding="utf-8")
            (root / "bin" / tool).chmod(0o755)
        for n, name in enumerate(channels, 1):
            (root / "hold" / name).mkdir(parents=True)
            (root / "hold" / name / "meta").write_text(META.format(n=n), encoding="utf-8")
        yield root


def hold(root, *args):
    path = f"{root / 'bin'}:{context.env()['PATH']}"
    return subprocess.run([str(context.BIN), *args], capture_output=True, text=True,
                          timeout=20, env=context.env(PATH=path,
                                                      SSH_HOLD_DIR=str(root / "hold"),
                                                      SCP_LOG=str(root / "scp.log")))


def scp_args(root):
    log = root / "scp.log"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else None


class TransferTests(unittest.TestCase):
    def test_upload_puts_the_remote_prefix_on_the_destination(self):
        with sandbox("web") as root:
            result = hold(root, "upload", "web", "a.txt", "/abs/b", "we:ird", "/tmp/")
            self.assertEqual(result.returncode, 0, result.stderr)
            args = scp_args(root)
        # Relative local paths gain ./ so a colon or a leading dash stays a file name.
        self.assertEqual(args[-4:], ["./a.txt", "/abs/b", "./we:ird", "ubuntu@10.0.0.1:/tmp/"])
        self.assertIn("-r", args)
        self.assertEqual(args[args.index("-P") + 1], "2211")
        self.assertIn(f"ControlPath={root / 'hold' / 'web' / 'sock'}", args)

    def test_download_puts_the_remote_prefix_on_the_sources(self):
        with sandbox("web") as root:
            result = hold(root, "download", "web", "/var/log/a", "/var/log/b", "out")
            self.assertEqual(result.returncode, 0, result.stderr)
            args = scp_args(root)
        self.assertEqual(args[-3:], ["ubuntu@10.0.0.1:/var/log/a", "ubuntu@10.0.0.1:/var/log/b", "./out"])

    def test_put_and_get_are_the_same_commands(self):
        with sandbox("web") as root:
            hold(root, "put", "web", "a", "/tmp/")
            self.assertEqual(scp_args(root)[-2:], ["./a", "ubuntu@10.0.0.1:/tmp/"])
            hold(root, "get", "web", "/tmp/a", "b")
            self.assertEqual(scp_args(root)[-2:], ["ubuntu@10.0.0.1:/tmp/a", "./b"])

    def test_transfer_uses_the_named_channel(self):
        with sandbox("web", "db") as root:
            hold(root, "upload", "db", "a", "/tmp/")
            self.assertEqual(scp_args(root)[-1], "ubuntu@10.0.0.2:/tmp/")

    def test_name_is_never_guessed(self):
        """With one channel open, a missing name must not turn a path into one."""
        with sandbox("web") as root:
            for args, message in ((("upload", "a.txt", "/tmp/"), "用法"),
                                  (("upload", "wbe", "a.txt", "/tmp/"), "没有名为 wbe 的通道"),
                                  (("download", "wbe", "/tmp/a", "."), "没有名为 wbe 的通道")):
                with self.subTest(args=args):
                    result = hold(root, *args)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(message, result.stderr)
                    self.assertIsNone(scp_args(root))

    def test_scp_failure_is_passed_on(self):
        with sandbox("web") as root:
            (root / "bin" / "scp").write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
            self.assertEqual(hold(root, "upload", "web", "a", "/tmp/").returncode, 7)


class ChannelTests(unittest.TestCase):
    def test_stop_removes_a_channel_whose_record_is_broken(self):
        with sandbox("web") as root:
            (root / "hold" / "web" / "meta").write_text("", encoding="utf-8")
            result = hold(root, "stop", "web")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((root / "hold" / "web").exists())

    def test_list_marks_a_broken_record_and_carries_on(self):
        for junk in ("", "TARGET=(\n"):  # 空文件；语法都不对的文件
            with self.subTest(junk=junk), sandbox("a", "b", "c") as root:
                (root / "hold" / "b" / "meta").write_text(junk, encoding="utf-8")
                result = hold(root, "list")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("ssh-hold stop b", result.stdout)
                # The channel after the broken one is still listed, and the broken
                # one has not borrowed the address of the channel before it.
                self.assertIn("ubuntu@10.0.0.3:2233", result.stdout)
                self.assertEqual(result.stdout.count("ubuntu@10.0.0.1:2211"), 1)

    def test_broken_record_is_never_used_to_reach_a_server(self):
        with sandbox("a", "b") as root:
            (root / "hold" / "b" / "meta").write_text("", encoding="utf-8")
            hold(root, "list")
            for args in (("run", "b", "--", "true"), ("upload", "b", "x", "/tmp/")):
                with self.subTest(args=args):
                    result = hold(root, *args)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("通道 b 的记录坏了", result.stderr)
            self.assertIsNone(scp_args(root))

    def test_start_rejects_names_made_of_dots(self):
        with sandbox() as root:
            for name in (".", "..", "..."):
                with self.subTest(name=name):
                    result = hold(root, "start", "-n", name, "-i", "/dev/null", "u@h")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("通道名", result.stderr)
            self.assertEqual([p.name for p in root.iterdir() if p.name not in ("bin", "hold")], [])

    def test_a_path_is_not_a_channel_name(self):
        with sandbox("web") as root:
            result = hold(root, "run", "../hold/web", "--", "true")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("没有名为 ../hold/web 的通道", result.stderr)

    def test_run_explains_a_missing_separator(self):
        with sandbox("web") as root:
            result = hold(root, "run", "uname", "-a")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("现有: web", result.stderr)
        self.assertIn("前面要加 --", result.stderr)


if __name__ == "__main__":
    unittest.main()
