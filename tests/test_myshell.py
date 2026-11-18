"""`link-myshell` and `run` on borrowed servers, against a stand-in for MyShell.

The real path is ssh-hold -> ssh -> curl on the MyShell machine -> MyShell. Here
`ssh` is a script that plays everything from ssh onwards: it reads which API
path the remote command was going to curl, appends the request to a log, and
answers from a file. A path with no answer on file behaves like MyShell not
running. A channel counts as open while a file sits where its socket would be.
Nothing leaves this machine.
"""

from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import context


FAKE_SSH = r'''#!/bin/sh
for last in "$@"; do
  case "$last" in ControlPath=*) sock="${last#ControlPath=}" ;; esac
done
case " $* " in
  *" -O check "*) [ -e "$sock" ]; exit ;;
  *" ControlMaster=yes "*)
    [ -n "${SSH_HOLD_PASSWORD:-}" ] && printf '%s\n' "$SSH_HOLD_PASSWORD" >>"$FAKE/passwords"
    : >"$sock"; exit 0 ;;
esac
case "$last" in *local-api.json*) ;; *) exit 0 ;; esac
path="$(printf '%s' "$last" | sed -n 's/.*baseUrl)\([^"]*\)".*/\1/p')"
method="$(printf '%s' "$last" | sed -n 's/.* -X \([A-Z]*\) .*/\1/p')"
printf '%s %s %s\n' "$method" "$path" "$(cat)" >>"$FAKE/requests"
reply="$FAKE/reply$(printf '%s' "$path" | tr / _)"
[ -f "$reply" ] || exit 7
cat "$reply"
printf '\n%s' "$(cat "$reply.status" 2>/dev/null || echo 200)"
'''

CONNECTIONS = [
    {"connectionId": "c1", "name": "生产-东京-1", "host": "jump.example", "port": 2222,
     "username": "ubuntu", "group": "生产", "tags": [], "canConnect": True},
    {"connectionId": "c2", "name": "Ops Manager: 10.1..2.3", "host": "jump.example", "port": 2222,
     "username": "ubuntu", "group": "生产", "tags": ["ops"], "canConnect": True},
    {"connectionId": "c3", "name": "self1", "host": "10.0.0.9", "port": 22,
     "username": "root", "group": "个人", "tags": ["dev"], "canConnect": True},
    {"connectionId": "c4", "name": "broken", "host": "10.0.0.8", "port": 22,
     "username": "root", "group": "生产", "tags": [], "canConnect": False},
]
STUDIO = "TARGET=me@100.64.0.1\nPORT=22\nSTARTED=now\nAUTH=password\nINSECURE=0\n"
DONE = {"status": "completed", "exitCode": 0, "stdout": "", "stderr": ""}


class Sandbox:
    def __init__(self, root):
        self.root = root
        self.hold = root / "hold"
        self.fake = root / "fake"

    def reply(self, path, body, status=None):
        target = self.fake / ("reply" + path.replace("/", "_"))
        target.write_text(json.dumps(body), encoding="utf-8")
        if status:
            Path(str(target) + ".status").write_text(str(status), encoding="utf-8")

    def run(self, *args, stdin=None):
        path = f"{self.root / 'bin'}:{context.env()['PATH']}"
        return subprocess.run([str(context.BIN), *args], capture_output=True, text=True, timeout=30,
                              input=stdin, env=context.env(PATH=path, SSH_HOLD_DIR=str(self.hold),
                                                           FAKE=str(self.fake)))

    def requests(self):
        log = self.fake / "requests"
        return [line.split(" ", 2) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []

    def bodies(self, path):
        return [json.loads(body) for _, seen, body in self.requests() if seen == path]

    def channels(self):
        return sorted(p.parent.name for p in self.hold.glob("*/meta"))

    def link(self, *args):
        result = self.run("link-myshell", "me@100.64.0.1", *args)
        assert result.returncode == 0, result.stderr
        return result


@contextmanager
def sandbox(studio=True):
    """MyShell with four saved servers, and (unless told otherwise) a channel to its machine."""
    with tempfile.TemporaryDirectory(prefix="shm-") as tmp:
        box = Sandbox(Path(tmp))
        for directory in (box.root / "bin", box.hold, box.fake):
            directory.mkdir()
        (box.root / "bin" / "ssh").write_text(FAKE_SSH, encoding="utf-8")
        (box.root / "bin" / "ssh").chmod(0o755)
        if studio:
            (box.hold / "studio").mkdir()
            (box.hold / "studio" / "meta").write_text(STUDIO, encoding="utf-8")
            (box.hold / "studio" / "sock").touch()
        box.reply("/v1/connections", {"connections": CONNECTIONS})
        box.reply("/v1/hubs/connect", {"hub": {"hubId": "hub_1"}, "reused": False})
        box.reply("/v1/hubs/exec", DONE)
        yield box


class LinkTests(unittest.TestCase):
    def test_links_everything_connectable_over_the_channel_already_open(self):
        with sandbox() as box:
            result = box.link()
            self.assertEqual(box.channels(), sorted(["生产-东京-1", "Ops-Manager-10.1..2.3", "self1", "studio"]))
            self.assertIn("经通道 studio", result.stdout)
            meta = (box.hold / "生产-东京-1" / "meta").read_text(encoding="utf-8")
        self.assertIn("VIA=studio\n", meta)
        self.assertIn("REMOTE_ID=c1\n", meta)
        self.assertIn("TARGET=ubuntu@jump.example\n", meta)

    def test_filters_narrow_what_is_exposed(self):
        for args, expected in ((("--group", "生产"), ["生产-东京-1", "Ops-Manager-10.1..2.3"]),
                               (("--tag", "dev", "--tag", "ops"), ["Ops-Manager-10.1..2.3", "self1"]),
                               (("--pick", "self1"), ["self1"]),
                               (("--group", "生产", "--tag", "ops"), ["Ops-Manager-10.1..2.3"])):
            with self.subTest(args=args), sandbox() as box:
                box.link(*args)
                self.assertEqual(box.channels(), sorted(expected + ["studio"]))

    def test_running_it_again_realigns_the_list(self):
        with sandbox() as box:
            box.link()
            result = box.link("--group", "个人")
            self.assertEqual(box.channels(), sorted(["self1", "studio"]))
            self.assertIn("已移除", result.stdout)

    def test_a_filter_that_matches_nothing_changes_nothing(self):
        with sandbox() as box:
            box.link("--group", "生产")
            result = box.run("link-myshell", "me@100.64.0.1", "--group", "生产x")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("现有分组: 个人 生产", result.stderr)
            self.assertEqual(len(box.channels()), 3)

    def test_a_name_already_in_use_is_not_taken_over(self):
        with sandbox() as box:
            (box.hold / "self1").mkdir()
            (box.hold / "self1" / "meta").write_text(STUDIO.replace("100.64.0.1", "9.9.9.9"), encoding="utf-8")
            box.link("--pick", "self1")
            self.assertEqual(box.channels(), sorted(["self1", "self1-2", "studio"]))
            self.assertNotIn("VIA", (box.hold / "self1" / "meta").read_text(encoding="utf-8"))
            # The second time round it is recognised by its id and keeps its name.
            box.link("--pick", "self1")
            self.assertEqual(box.channels(), sorted(["self1", "self1-2", "studio"]))

    def test_opens_the_channel_itself_when_there_is_none(self):
        for args, stdin in ((("s3cret, pw",), None), (("--password-stdin",), "s3cret, pw\n")):
            with self.subTest(args=args), sandbox(studio=False) as box:
                result = box.run("link-myshell", "me@100.64.0.1", *args, "--group", "生产", stdin=stdin)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(box.channels(), sorted(["生产-东京-1", "Ops-Manager-10.1..2.3", "myshell"]))
                self.assertEqual((box.fake / "passwords").read_text(encoding="utf-8"), "s3cret, pw\n")
                self.assertNotIn("s3cret", result.stdout + result.stderr)

    def test_myshell_not_running_is_said_plainly(self):
        with sandbox() as box:
            (box.fake / "reply_v1_connections").unlink()
            result = box.run("link-myshell", "me@100.64.0.1")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("没在运行", result.stderr)
            self.assertEqual(box.channels(), sorted(["studio"]))


class RunTests(unittest.TestCase):
    def test_output_and_exit_code_come_back(self):
        with sandbox() as box:
            box.link()
            box.reply("/v1/hubs/exec", dict(DONE, exitCode=3, stdout="out\n", stderr="err\n"))
            result = box.run("run", "生产-东京-1", "--", "echo", "a b", "|", "wc")
            self.assertEqual((result.returncode, result.stdout, result.stderr), (3, "out\n", "err\n"))
            self.assertEqual(box.bodies("/v1/hubs/connect"), [{"connectionId": "c1"}])
            # Joined with spaces and left to the remote shell, exactly as ssh would.
            self.assertEqual(box.bodies("/v1/hubs/exec"),
                             [{"hubId": "hub_1", "command": "echo a b | wc", "timeoutMs": 120000}])

    def test_binary_output_is_decoded(self):
        with sandbox() as box:
            box.link()
            box.reply("/v1/hubs/exec", dict(DONE, stdout="/wABeA==", stdoutEncoding="base64"))
            path = f"{box.root / 'bin'}:{context.env()['PATH']}"
            raw = subprocess.run([str(context.BIN), "run", "self1", "--", "cat", "blob"], capture_output=True,
                                 timeout=30, env=context.env(PATH=path, SSH_HOLD_DIR=str(box.hold),
                                                             FAKE=str(box.fake)))
        self.assertEqual(raw.stdout, b"\xff\x00\x01x")

    def test_a_command_that_runs_too_long_is_reported_as_such(self):
        with sandbox() as box:
            box.link()
            box.reply("/v1/hubs/exec", {"status": "timed_out", "exitCode": None, "stdout": "partial\n",
                                        "stderr": "", "remoteProcessMayStillRun": True})
            result = box.run("run", "self1", "--", "sleep", "999")
        self.assertEqual(result.returncode, 124)
        self.assertEqual(result.stdout, "partial\n")
        self.assertIn("远端进程可能还在跑", result.stderr)

    def test_a_refusal_from_myshell_is_passed_on(self):
        with sandbox() as box:
            box.link()
            box.reply("/v1/hubs/connect", {"error": {"code": "connection_failed", "message": "无法建立 SSH 通道"}}, 502)
            result = box.run("run", "self1", "--", "true")
        self.assertEqual(result.returncode, 1)
        self.assertIn("无法建立 SSH 通道（connection_failed）", result.stderr)

    def test_only_run_is_offered(self):
        with sandbox() as box:
            box.link()
            before = len(box.requests())
            for args in (("shell", "self1"), ("upload", "self1", "a", "/tmp/"), ("download", "self1", "/tmp/a", ".")):
                with self.subTest(args=args):
                    result = box.run(*args)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("只支持 run", result.stderr)
            self.assertEqual(len(box.requests()), before)

    def test_list_says_where_a_borrowed_channel_goes_through(self):
        with sandbox() as box:
            box.link("--pick", "self1")
            result = box.run("list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("经由: studio 上的 MyShell（畅通），只支持 run", result.stdout)


class StopTests(unittest.TestCase):
    def test_stopping_a_borrowed_channel_closes_the_idle_hub_behind_it(self):
        for terminals, closed in ((0, [{"hubId": "hub_1"}]), (1, [])):
            with self.subTest(terminals=terminals), sandbox() as box:
                box.link()
                box.reply("/v1/hubs", {"hubs": [{"hubId": "hub_1", "connectionId": "c3", "terminalCount": terminals},
                                                {"hubId": "hub_2", "connectionId": "c1", "terminalCount": 0}]})
                box.reply("/v1/hubs/close", {"ok": True})
                self.assertEqual(box.run("stop", "self1").returncode, 0)
                self.assertNotIn("self1", box.channels())
                self.assertEqual(box.bodies("/v1/hubs/close"), closed)

    def test_stopping_still_works_when_myshell_cannot_be_reached(self):
        with sandbox() as box:
            box.link()
            result = box.run("stop", "self1")  # no /v1/hubs answer on file
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("self1", box.channels())

    def test_stopping_the_channel_takes_what_was_borrowed_through_it(self):
        with sandbox() as box:
            (box.hold / "other").mkdir()
            (box.hold / "other" / "meta").write_text(STUDIO.replace("100.64.0.1", "9.9.9.9"), encoding="utf-8")
            box.link()
            result = box.run("stop", "studio")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(box.channels(), sorted(["other"]))


class NameTests(unittest.TestCase):
    def test_names_may_use_any_script_but_no_ascii_punctuation(self):
        with sandbox(studio=False) as box:
            self.assertEqual(box.run("start", "-n", "测试-机.1", "--key", "u@h").returncode, 0)
            self.assertEqual(box.channels(), sorted(["测试-机.1"]))
            for name in ("a b", "a/b", "a:b", "a$b", "-x", ".."):
                with self.subTest(name=name):
                    result = box.run("start", "-n", name, "--key", "u@h")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("通道名", result.stderr)
            self.assertEqual(box.channels(), sorted(["测试-机.1"]))


if __name__ == "__main__":
    unittest.main()
