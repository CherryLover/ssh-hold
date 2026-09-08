"""Read JumpServer credentials; only explicit --check displays the password."""

import argparse
import getpass
import json
from datetime import datetime, timezone
import re
import shutil
import subprocess
import sys


LABELS = ("名称", "主机", "端口", "用户名", "密码", "协议", "过期时间")


def parse_clipboard(text, now=None, check_expiry=True):
    fields = {}
    pattern = r"^(" + "|".join(LABELS) + r")([ \t]*\t| *[:：] ?| +)(.*)$"
    for line in text.lstrip("\ufeff").splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(pattern, line.lstrip())
        if not match:
            raise ValueError("剪贴板格式不正确，请复制完整的连接信息")
        key, separator, value = match.groups()
        # Password whitespace is data, not formatting. Never silently trim it.
        if key != "密码":
            value = value.strip()
        if key in fields:
            raise ValueError("剪贴板有重复字段，请只复制一台机器的信息")
        if not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("字段为空或含有不支持的字符")
        fields[key] = value
    for key in ("主机", "端口", "用户名", "密码", "协议"):
        if key not in fields:
            raise ValueError("缺少字段：" + key)
    if fields["协议"].lower() != "ssh":
        raise ValueError("只支持 ssh 协议")
    port = fields["端口"]
    if not re.fullmatch(r"[0-9]{1,5}", port) or not 1 <= int(port) <= 65535:
        raise ValueError("端口必须在 1 到 65535 之间")
    fields["端口"] = str(int(port))
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:\[\]-]*", fields["主机"]):
        raise ValueError("主机格式不正确")
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9._-]*", fields["用户名"]):
        raise ValueError("用户名格式不正确")
    if "过期时间" in fields:
        try:
            expires = datetime.strptime(fields["过期时间"], "%Y/%m/%d %H:%M:%S %z")
        except ValueError:
            raise ValueError("过期时间格式不正确") from None
        if check_expiry and expires <= (now or datetime.now(timezone.utc)):
            raise ValueError("连接信息已过期，请重新复制新的信息")
    # Keep the asset IP in the name so similarly named assets remain distinct.
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", fields.get("名称", fields["主机"]))
    fields["name"] = name.strip(".-_")[:64].rstrip(".-_") or "jump-host"
    return fields


def compare_passwords(parsed, entered):
    if parsed == entered:
        return "密码完全一致。"
    summary = f"密码不一致：剪贴板 {len(parsed)} 个字符，手动输入 {len(entered)} 个字符。"
    if parsed.strip() == entered.strip():
        return summary + "\n差异仅在首尾空白。"
    index = next((i for i, pair in enumerate(zip(parsed, entered), 1)
                  if pair[0] != pair[1]), min(len(parsed), len(entered)) + 1)
    return summary + f"\n从第 {index} 个字符开始不同（不显示字符内容）。"


def main():
    parser = argparse.ArgumentParser(description="读取剪贴板中的跳板机连接信息")
    parser.add_argument("script", help=argparse.SUPPRESS)
    parser.add_argument("-n", "--name")
    checks = parser.add_mutually_exclusive_group()
    checks.add_argument("--check", action="store_true", help="显示全部解析字段（包括明文密码），不连接")
    checks.add_argument("--verify-password", action="store_true", help="与手动输入的密码本地比较，不联网，过期信息也可核对")
    parser.add_argument("--insecure", action="store_true")
    parser.add_argument("--debug", action="store_true", help="显示 SSH 连接过程，不显示密码，不自动重试")
    parser.add_argument("--keep-password-spaces", action="store_true", help="密码本身包含首尾空白时原样保留")
    args = parser.parse_args()
    if args.name is not None and (
        not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", args.name)
        or args.name in (".", "..")
    ):
        parser.error("通道名只能用字母、数字、点、下划线、短横线，最长 64 字符")
    if not shutil.which("pbpaste"):
        raise ValueError("找不到 pbpaste；目前 paste 仅支持 macOS 剪贴板")
    clipboard = subprocess.run(["pbpaste"], capture_output=True, check=False)
    if clipboard.returncode:
        raise ValueError("读取剪贴板失败")
    try:
        fields = parse_clipboard(clipboard.stdout.decode("utf-8"), check_expiry=not args.verify_password)
    except UnicodeDecodeError:
        raise ValueError("剪贴板不是有效的 UTF-8 文本") from None
    name = args.name or fields["name"]
    target = fields["用户名"] + "@" + fields["主机"]
    if args.verify_password:
        if not sys.stdin.isatty():
            raise ValueError("请在终端中运行密码核对；不会从管道读取或显示密码")
        print("仅在本机比较密码，不连接服务器、不消耗凭据；允许核对已过期信息。", flush=True)
        entered = getpass.getpass("请输入你手动登录时使用的密码（不显示）：")
        print(compare_passwords(fields["密码"], entered))
        return 0 if fields["密码"] == entered else 1
    raw_password = fields["密码"]
    fields["密码"] = raw_password if args.keep_password_spaces else raw_password.strip()
    if not fields["密码"]:
        raise ValueError("密码去除首尾空白后为空，不连接")
    if args.check:
        print("注意：以下包含明文密码，请勿截图或转发。")
        print("解析结果（引号用于标出内容边界，不属于字段本身）：")
        for label in LABELS:
            print(label + "：" + (json.dumps(fields[label], ensure_ascii=False)
                                  if label in fields else "（未提供）"))
        password = fields["密码"]
        print("剪贴板原始密码：" + json.dumps(raw_password, ensure_ascii=False))
        print("实际发送的密码：" + json.dumps(password, ensure_ascii=False))
        print(f"原始密码长度：{len(raw_password)} 个字符；实际密码长度：{len(password)} 个字符")
        print(f"原始密码开头空格：{len(raw_password) - len(raw_password.lstrip(' '))} 个；"
              f"末尾空格：{len(raw_password) - len(raw_password.rstrip(' '))} 个")
        print("通道名：" + name)
        print("格式和有效期检查通过，未验证登录，未连接。")
        return 0
    print(f"识别到通道：{name}\n目标：{target}:{fields['端口']}", flush=True)
    if raw_password != fields["密码"]:
        print(f"已去除密码首尾空白：{len(raw_password)} -> {len(fields['密码'])} 个字符", flush=True)
    if "过期时间" in fields:
        print("过期时间：" + fields["过期时间"], flush=True)
    command = [args.script, "start", "-n", name, "-p", fields["端口"], "--password-stdin"]
    if args.insecure:
        command.append("--insecure")
    if args.debug:
        command.extend(["-o", "LogLevel=DEBUG1"])
    command.append(target)
    return subprocess.run(command, input=fields["密码"] + "\n", text=True).returncode


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError) as error:
        print("ssh-hold: " + str(error), file=sys.stderr)
        sys.exit(1)
