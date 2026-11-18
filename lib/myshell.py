"""Borrow the servers saved in a MyShell app that runs on another machine.

MyShell keeps the SSH credentials and does the connecting. What reaches this
machine is a list of names, written down as channels that only know how to
`run`. Every request travels as a curl command over an ordinary ssh-hold
channel to the machine MyShell runs on: its API listens on that machine's
loopback only, and its token is read there and never copied here.

    myshell.py <ssh-hold> link [options] user@host [password]
    myshell.py <ssh-hold> exec <via-channel> <connection-id> <command>
    myshell.py <ssh-hold> close <via-channel> <connection-id>
"""

import argparse
import base64
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

# Runs on the MyShell machine. Exit 97 means MyShell has never started there.
REMOTE = r'''F="$HOME/Library/Application Support/uk.flyooo.myshell/local-api.json"
[ -r "$F" ] || exit 97
k() { sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/p" "$F" | head -1; }
exec curl -sS --max-time %d -X %s -H "Authorization: Bearer $(k token)" -H "Content-Type: application/json" %s -w "\n%%{http_code}" "$(k baseUrl)%s"'''

MAX_SECONDS = 120  # MyShell's ceiling for a synchronous command
CURL_FAILURES = {
    97: "那台机器上没找到 MyShell 的 local-api.json，MyShell 装了并且启动过吗",
    7: "连不上 MyShell 的本地接口，它现在没在运行",
    28: "MyShell 的本地接口迟迟没有回应",
}


class Refused(Exception):
    """Something the user has to act on; the message is the whole story."""


def hold(script, *args, **kwargs):
    return subprocess.run([script, *args], **kwargs)


def api(script, via, method, path, body=None, wait=20):
    """One request to MyShell, sent through the channel `via`. Returns the JSON."""
    remote = REMOTE % (wait, method, "" if body is None else "--data-binary @-", path)
    sent = hold(script, "run", via, "--", remote, stdout=subprocess.PIPE,
                input=b"" if body is None else json.dumps(body).encode("utf-8"))
    if sent.returncode:
        # Anything else already explained itself on stderr: a dead channel, a curl error.
        raise Refused(CURL_FAILURES.get(sent.returncode, f"经通道 {via} 调用 MyShell 失败"))
    text, _, status = sent.stdout.decode("utf-8", "replace").rpartition("\n")
    try:
        reply = json.loads(text)
    except ValueError:
        raise Refused(f"MyShell 返回了看不懂的内容（HTTP {status}）") from None
    if not status.startswith("2"):
        error = reply.get("error") or {}
        raise Refused(f"MyShell 拒绝了请求：{error.get('message', text)}（{error.get('code', status)}）")
    return reply


# ───────────────────────── exec ─────────────────────────

def run_remote(script, via, remote_id, command):
    """Run one command on a borrowed server; the exit code is the remote one."""
    wanted = os.environ.get("SSH_HOLD_MYSHELL_TIMEOUT", "")
    seconds = min(max(int(wanted), 1), MAX_SECONDS) if wanted.isdigit() else MAX_SECONDS
    hub = api(script, via, "POST", "/v1/hubs/connect", {"connectionId": remote_id})["hub"]["hubId"]
    result = api(script, via, "POST", "/v1/hubs/exec",
                 {"hubId": hub, "command": command, "timeoutMs": seconds * 1000}, wait=seconds + 15)
    for name, stream in (("stdout", sys.stdout), ("stderr", sys.stderr)):
        data = result.get(name) or ""
        raw = base64.b64decode(data) if result.get(name + "Encoding") == "base64" else data.encode("utf-8")
        stream.buffer.write(raw)
        stream.flush()
        if result.get(name + "Truncated"):
            print(f"ssh-hold: {name} 太长，被 MyShell 截断了", file=sys.stderr)
    if result.get("status") == "completed":
        code = result.get("exitCode")
        return 1 if code is None else code
    if result.get("status") == "timed_out":
        still = "，远端进程可能还在跑" if result.get("remoteProcessMayStillRun") else ""
        print(f"ssh-hold: 命令 {seconds} 秒内没跑完{still}。经 MyShell 转发的命令最长 {MAX_SECONDS} 秒，"
              "更久的请放到后台跑（nohup … &）再回来查结果。", file=sys.stderr)
        return 124
    print(f"ssh-hold: MyShell 没能执行这条命令（{result.get('status')}）", file=sys.stderr)
    return 1


def close_hub(script, via, remote_id):
    """Drop MyShell's connection behind a channel that is being stopped.

    MyShell keeps a hub open once it has been asked to connect, which is what
    makes the next `run` fast. A hub somebody has a terminal on is theirs.
    """
    for hub in api(script, via, "GET", "/v1/hubs")["hubs"]:
        if hub.get("connectionId") == remote_id and not hub.get("terminalCount"):
            api(script, via, "POST", "/v1/hubs/close", {"hubId": hub["hubId"]})
    return 0


# ───────────────────────── link ─────────────────────────

def read_meta(path):
    """The KEY=value lines ssh-hold writes, shell quoting undone."""
    fields = {}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return fields
    for line in lines:
        key, found, value = line.partition("=")
        try:
            if found:
                fields[key] = "".join(shlex.split(value))
        except ValueError:
            pass
    return fields


def channel_name(text, taken):
    """A legal, unused channel name that still reads like the MyShell one."""
    name = re.sub(r"-{2,}", "-", re.sub(r"[^\w.-]", "-", text)).strip("-")
    if not name.strip("."):
        name = "myshell"
    candidate, n = name, 1
    while candidate in taken:
        n += 1
        candidate = f"{name}-{n}"
    return candidate


def open_channel(script, args):
    command = ["start", "-n", args.name, "-p", str(args.port)]
    command += ["--insecure"] if args.insecure else []
    command += ["-i", args.identity] if args.identity else []
    password = sys.stdin.readline().rstrip("\n") if args.password_stdin else args.password
    if password:
        command.append("--password-stdin")
    opened = hold(script, *command, args.target, input=(password + "\n").encode("utf-8") if password else None)
    if opened.returncode:
        raise SystemExit(opened.returncode)


def keep(connection, args):
    """Each kind of filter that was given must be satisfied; within a kind, any value will do."""
    return (connection.get("canConnect", True)
            and (not args.group or connection.get("group") in args.group)
            and (not args.tag or set(connection.get("tags") or []) & set(args.tag))
            and (not args.pick or connection.get("name") in args.pick))


def link(script, args):
    base = Path(os.environ.get("SSH_HOLD_DIR") or Path.home() / ".ssh" / "hold")
    metas = {d.name: read_meta(d / "meta") for d in sorted(base.glob("*")) if (d / "meta").is_file()}

    # A channel to that machine may be open already; opening a second one buys nothing.
    via = next((name for name, meta in metas.items()
                if not meta.get("VIA") and meta.get("TARGET") == args.target
                and meta.get("PORT") == str(args.port)
                and not hold(script, "run", name, "--", "true", capture_output=True).returncode), None)
    if via is None:
        via = args.name
        open_channel(script, args)

    connections = api(script, via, "GET", "/v1/connections")["connections"]
    wanted = [c for c in connections if keep(c, args)]
    if not wanted:
        groups = sorted({c.get("group") or "（未分组）" for c in connections})
        raise Refused(f"MyShell 里有 {len(connections)} 台服务器，但没有一台符合条件，什么都没改。"
                      f"现有分组: {' '.join(groups)}")

    # A server keeps the name it was given last time, whatever has been added around it since.
    ours = {meta.get("REMOTE_ID"): name for name, meta in metas.items() if meta.get("VIA") == via}
    taken = (set(metas) | {via}) - set(ours.values())
    started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    kept = []
    for c in wanted:
        name = ours.get(c["connectionId"]) or channel_name(c["name"], taken)
        taken.add(name)
        kept.append(name)
        fields = {"TARGET": f"{c['username']}@{c['host']}", "PORT": c["port"], "NAME": name,
                  "STARTED": started, "AUTH": "myshell", "INSECURE": 0, "VIA": via,
                  "REMOTE_ID": c["connectionId"], "REMOTE_NAME": c["name"], "GROUP": c.get("group") or ""}
        (base / name).mkdir(mode=0o700, exist_ok=True)
        meta = base / name / "meta"
        meta.touch(mode=0o600)
        meta.write_text("".join(f"{k}={shlex.quote(str(v))}\n" for k, v in fields.items()), encoding="utf-8")
        print(f"  {name}    {fields['TARGET']}:{c['port']}    [{fields['GROUP']}]")

    dropped = sorted(set(ours.values()) - set(kept))
    for name in dropped:
        shutil.rmtree(base / name)
    print(f"\n已接入 {args.target} 上的 MyShell（经通道 {via}），登记了 {len(kept)} 台。")
    if dropped:
        print("不再符合条件、已移除: " + " ".join(dropped))
    print(f"\n之后可以这样用：\n  ssh-hold list\n  ssh-hold run {kept[0]} -- uname -a")
    return 0


def parse_link(argv):
    parser = argparse.ArgumentParser(
        prog="ssh-hold link-myshell",
        description="把另一台机器上 MyShell 里存的服务器登记成通道。凭据留在那台机器上，"
                    "登记来的通道只支持 run。重跑同一条命令就是重新对齐列表。")
    parser.add_argument("target", metavar="用户@地址", help="跑着 MyShell 的那台机器")
    parser.add_argument("password", metavar="密码", nargs="?",
                        help="那台机器的登录密码。会留在命令历史里，介意就用 --password-stdin")
    parser.add_argument("-n", "--name", default="myshell", help="到那台机器的通道叫什么，默认 myshell")
    parser.add_argument("-p", "--port", type=int, default=22, help="那台机器的 SSH 端口，默认 22")
    parser.add_argument("-i", "--identity", metavar="文件", help="用密钥登录那台机器")
    parser.add_argument("--password-stdin", action="store_true", help="从标准输入读密码")
    parser.add_argument("--insecure", action="store_true", help="不校验那台机器的主机指纹")
    parser.add_argument("--group", action="append", metavar="分组", help="只登记这个分组，可重复")
    parser.add_argument("--tag", action="append", metavar="标签", help="只登记带这个标签的，可重复")
    parser.add_argument("--pick", action="append", metavar="名字", help="只登记 MyShell 里叫这个名字的，可重复")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"(?=.*[^.])(?!-)(?:[A-Za-z0-9._-]|[^\x00-\x7f])+", args.name):
        parser.error("通道名不能有空格、斜杠和标点（点、下划线、短横线除外），不能以短横线开头")
    return args


def main(argv):
    script, action, rest = argv[1], argv[2], argv[3:]
    if action == "link":
        return link(script, parse_link(rest))
    return {"exec": run_remote, "close": close_hub}[action](script, *rest)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except (Refused, OSError) as error:
        print("ssh-hold: " + str(error), file=sys.stderr)
        sys.exit(1)
