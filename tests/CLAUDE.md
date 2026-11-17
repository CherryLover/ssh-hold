# tests/

全部用标准库 `unittest`，从本目录运行（`make test` / `make test-wire`）。被测对象永远是这份源码树，不是 `~/.local` 里装好的那份。

```
tests/
├── context.py      定位被测程序和运行库，生成子进程环境；其余文件都 import 它
├── test_paste.py   lib/paste.py 的剪贴板解析：字段、分隔符、过期、密码空白
├── test_skill.py   ssh-hold skill：临时 HOME 里验证自动识别、--dir、备份、幂等
├── test_cli.py     通道解析与 upload / download：ssh、scp 换成替身，验参数不验传输
└── test_wire.py    回环上起 paramiko 假服务端，验证密码原样送达（需要 uv，单独跑）
```

## 边界

- `context.py` 是唯一知道「程序在哪」的地方。`SSH_HOLD_BIN` 指向别的可执行文件（比如单文件版）时，同一套用例直接复用。
- `test_paste` / `test_skill` / `test_cli` 不联网、不碰真实 `~/.ssh` 和 `~/.claude`，都在临时目录里摆场景。
- `test_cli` 的替身放在 `PATH` 最前面：假 `ssh` 一律成功，于是有记录的通道都算畅通；假 `scp` 把参数写进文件。真实传输没有自动化用例，改了 `cmd_transfer` 要手工对着真服务器传一次。
- 新增测试文件要同时加进 `Makefile` 的 `test` 目标，那里是显式列名字的。

## 变更

- 2026-11-17：新增 `test_cli.py`，覆盖 upload / download 和通道记录的几处修复。
