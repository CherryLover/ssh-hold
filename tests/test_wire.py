"""Loopback-only authentication tests with the real SSH password transport.

Run: uv run --with paramiko python -m unittest -v test_wire.py
"""

import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import unittest

import context

import paramiko


class WireTests(unittest.TestCase):
    def test_successful_connection_and_reuse(self):
        key = paramiko.RSAKey.generate(2048)
        for debug in (False, True):
            with self.subTest(debug=debug):
                self.check_password(key, " fake-$ecret;' value ", debug, authenticate=True)

    def test_password_received_by_server(self):
        key = paramiko.RSAKey.generate(2048)
        for password in ("fake-ABC123", " fake-$ecret;' value ", "quote\\\"$test"):
            for debug in (False, True):
                with self.subTest(spaces=password.startswith(" "), debug=debug):
                    self.check_password(key, password, debug)

    def check_password(self, key, password, debug, authenticate=False, keep_spaces=False):
        received = []
        expected = password if keep_spaces else password.strip()

        class Server(paramiko.ServerInterface):
            def get_allowed_auths(self, username):
                return "password,publickey"

            def check_auth_password(self, username, value):
                received.append((username, value))
                if authenticate and value == expected:
                    return paramiko.AUTH_SUCCESSFUL
                return paramiko.AUTH_FAILED

            def check_channel_request(self, kind, chanid):
                return paramiko.OPEN_SUCCEEDED

            def check_channel_exec_request(self, channel, command):
                channel.test_command = command
                return True

        with socket.socket() as listener, tempfile.TemporaryDirectory(prefix="shw-") as tmp:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(10)
            port = listener.getsockname()[1]
            errors = []

            def serve():
                try:
                    client, _ = listener.accept()
                    with paramiko.Transport(client) as transport:
                        transport.add_server_key(key)
                        transport.start_server(server=Server())
                        if not authenticate:
                            transport.join(10)
                        else:
                            while transport.is_active():
                                channel = transport.accept(1)
                                if channel is None:
                                    continue
                                for _ in range(100):
                                    if hasattr(channel, 'test_command'):
                                        break
                                    threading.Event().wait(0.01)
                                if getattr(channel, 'test_command', b'') != b'true':
                                    channel.sendall(b'local-test-ok\n')
                                channel.send_exit_status(0)
                                channel.close()
                except Exception as error:
                    errors.append(type(error).__name__)

            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            root = Path(tmp)
            pbpaste = root / "pbpaste"
            pbpaste.write_text("#!/usr/bin/env python3\nimport os\nprint(os.environ['TEST_CLIPBOARD'])\n")
            pbpaste.chmod(0o700)
            clipboard = (f"名称\tlocal-test\n主机\t127.0.0.1\n端口\t{port}\n"
                         f"用户名\tJMS-local-test\n密码\t{password}\n协议\tssh\n")
            env = context.env(PATH=tmp + os.pathsep + os.environ["PATH"],
                              SSH_HOLD_DIR=str(root / "hold"), TEST_CLIPBOARD=clipboard)
            command = [str(context.BIN), "paste", "--insecure"]
            if debug:
                command.append("--debug")
            if keep_spaces:
                command.append("--keep-password-spaces")
            try:
                result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=15)
                if authenticate:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    reused = subprocess.run([command[0], 'run', 'local-test', '--', 'echo local-test-ok'],
                                            capture_output=True, text=True, env=env, timeout=10)
                    self.assertEqual(reused.returncode, 0, reused.stderr)
                    self.assertEqual(reused.stdout, 'local-test-ok\n')
            finally:
                if authenticate:
                    subprocess.run([command[0], 'stop', 'local-test'], capture_output=True,
                                   text=True, env=env, timeout=10)
            thread.join(12)
            self.assertFalse(thread.is_alive())
            self.assertFalse(errors, errors)
            if not authenticate:
                self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(password, result.stdout + result.stderr)
            self.assertEqual(received, [("JMS-local-test", expected)])

    def test_explicit_password_spaces(self):
        self.check_password(paramiko.RSAKey.generate(2048), " keep spaces ", False,
                            authenticate=True, keep_spaces=True)


if __name__ == "__main__":
    unittest.main()
