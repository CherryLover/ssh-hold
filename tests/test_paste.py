from datetime import datetime, timezone
from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import context

import paste


SAMPLE = """名称\tOpenai-proxy(172.26.10.104)
主机\tops.example.test
端口\t2222
用户名\tJMS-test-user
密码\tfake-$ecret;' value 
协议\tssh
过期时间\t2099/09/08 09:19:38 +0800
"""


class PasteTests(unittest.TestCase):
    def test_local_password_comparison(self):
        for entered, expected in (("fake-$ecret;' value ", "完全一致"),
                                  ("fake-$ecret;' value", "差异仅在首尾空白"),
                                  ("wrong-password", "第 1 个字符")):
            output = io.StringIO()
            clipboard = subprocess.CompletedProcess(["pbpaste"], 0,
                SAMPLE.replace("2099/09/08", "2020/09/08").encode())
            with patch("sys.argv", ["paste.py", "ssh-hold", "--verify-password"]), \
                 patch("paste.shutil.which", return_value="pbpaste"), \
                 patch("paste.subprocess.run", return_value=clipboard) as run, \
                 patch("sys.stdin.isatty", return_value=True), \
                 patch("paste.getpass.getpass", return_value=entered), redirect_stdout(output):
                result = paste.main()
            self.assertIn(expected, output.getvalue())
            self.assertEqual(result, 0 if entered.endswith("value ") else 1)
            self.assertNotIn(entered, output.getvalue())
            run.assert_called_once_with(["pbpaste"], capture_output=True, check=False)

    def test_formats(self):
        for separator in ("\t", "  ", ": ", "："):
            for newline in ("\n", "\r\n"):
                fields = paste.parse_clipboard(SAMPLE.replace("\t", separator).replace("\n", newline))
                self.assertEqual(fields["name"], "Openai-proxy-172.26.10.104")
                self.assertEqual(fields["密码"], "fake-$ecret;' value ")

    def test_password_whitespace(self):
        for password in (" leading", "trailing ", " both ", ":prefix", "a\\b$'\"c"):
            fields = paste.parse_clipboard(SAMPLE.replace("fake-$ecret;' value ", password))
            self.assertEqual(fields["密码"], password)

    def test_reject_invalid(self):
        invalid = ["", SAMPLE + "端口\t22\n", SAMPLE.replace("ssh", "rdp"),
                   SAMPLE.replace("2222", "65536"), SAMPLE.replace("2222", "0"),
                   SAMPLE.replace("ops.example.test", "$(touch /tmp/bad)"),
                   SAMPLE.replace("JMS-test-user", "-oProxyCommand=bad"),
                   SAMPLE.replace("2099/09/08", "2020/09/08"),
                   SAMPLE.replace("2099/09/08", "nonsense"),
                   SAMPLE.replace("协议\tssh\n", ""), SAMPLE + "unrecognized\n"]
        for value in invalid:
            with self.subTest(value=invalid.index(value)), self.assertRaises(ValueError):
                paste.parse_clipboard(value)

    def test_expiry_boundary(self):
        with self.assertRaises(ValueError):
            paste.parse_clipboard(SAMPLE, datetime(2099, 9, 8, 1, 19, 38, tzinfo=timezone.utc))

    def test_leading_zero_port(self):
        self.assertEqual(paste.parse_clipboard(SAMPLE.replace("2222", "00022"))["端口"], "22")

    def test_full_shell_entry_and_password_transport(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binaries = {
                "pbpaste": "#!/usr/bin/env python3\nimport os\nprint(os.environ['TEST_CLIPBOARD'])\n",
                "ssh": """#!/usr/bin/env python3
import os, sys, subprocess
from pathlib import Path
connected = Path(os.environ['SSH_HOLD_DIR']) / 'connected'
if sys.argv[1] == '-O':
    sys.exit(0 if connected.exists() else 1)
if os.environ.get('TEST_DEBUG'):
    assert 'LogLevel=DEBUG1' in sys.argv
assert os.environ['SSH_ASKPASS_REQUIRE'] == 'force'
password = subprocess.check_output([os.environ['SSH_ASKPASS'], 'Password: ']).decode().rstrip('\\n')
assert password == "fake-$ecret;' value"
connected.touch()
""",
            }
            for name, source in binaries.items():
                path = root / name
                path.write_text(source)
                path.chmod(0o700)
            env = context.env(PATH=tmp + os.pathsep + os.environ["PATH"],
                              SSH_HOLD_DIR=str(root / "hold"), TEST_CLIPBOARD=SAMPLE)
            script = str(context.BIN)
            def run(*args):
                return subprocess.run([script, "paste", *args], env=env, capture_output=True, text=True, timeout=10)
            checked = run("--check")
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertIn('剪贴板原始密码："fake-$ecret;\' value "', checked.stdout)
            self.assertIn('实际发送的密码："fake-$ecret;\' value"', checked.stdout)
            self.assertIn('名称："Openai-proxy(172.26.10.104)"', checked.stdout)
            self.assertIn('主机："ops.example.test"', checked.stdout)
            self.assertIn('端口："2222"', checked.stdout)
            self.assertIn('用户名："JMS-test-user"', checked.stdout)
            self.assertIn('协议："ssh"', checked.stdout)
            self.assertIn('过期时间："2099/09/08 09:19:38 +0800"', checked.stdout)
            self.assertIn('密码长度：20 个字符', checked.stdout)
            self.assertIn('实际密码长度：19 个字符', checked.stdout)
            self.assertIn('末尾空格：1 个', checked.stdout)
            self.assertIn('未验证登录，未连接', checked.stdout)
            self.assertIn('请勿截图或转发', checked.stdout)
            self.assertFalse((root / "hold").exists())
            connected = run()
            self.assertEqual(connected.returncode, 0, connected.stderr)
            self.assertIn("通道已撑开", connected.stdout)
            meta = root / "hold/Openai-proxy-172.26.10.104/meta"
            self.assertIn("PORT=2222", meta.read_text())
            self.assertNotIn("fake-", connected.stdout + connected.stderr + meta.read_text())
            duplicate = run()
            self.assertNotEqual(duplicate.returncode, 0)
            self.assertIn("已经在了", duplicate.stderr)
            self.assertNotEqual(run("-n", "..").returncode, 0)
            (root / "hold/connected").unlink()
            env["TEST_DEBUG"] = "1"
            debugged = run("--debug")
            self.assertEqual(debugged.returncode, 0, debugged.stderr)
            self.assertNotIn("fake-", debugged.stdout + debugged.stderr)
            env["TEST_CLIPBOARD"] = SAMPLE.replace("2099/09/08", "2020/09/08")
            self.assertNotEqual(run().returncode, 0)


if __name__ == "__main__":
    unittest.main()
