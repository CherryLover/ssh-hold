# lib/

主脚本 `bin/ssh-hold` 用到时才去找的运行时文件。安装后在 `<前缀>/lib/ssh-hold/`，单文件版把它们内嵌在脚本里，用到时解到缓存目录。

```
lib/
├── askpass      ssh 来要密码时由它回答：把环境变量里的密码打出来，4 行
├── paste.py     读剪贴板里 JumpServer 的连接信息，校验后回调 ssh-hold start
└── myshell.py   借用另一台机器上 MyShell 里的服务器：登记（link）、代为执行（exec）、关连接（close）
```

## 边界

- 两个 python 脚本都只用标准库，第一个参数是 `ssh-hold` 自己的路径。它们不直接碰 ssh，要连什么都回调 `ssh-hold start` / `ssh-hold run`，于是认证、通道解析、断线提示只有主脚本那一份。
- 主脚本经 `run_lib` 调它们，不知道它们内部做什么；它们经 `meta` 文件和主脚本共享状态。
- `myshell.py` 写的 `meta` 比普通通道多 `VIA`（经哪条通道）和 `REMOTE_ID`（MyShell 里的连接 id）。主脚本只看 `VIA` 是否为空来区分两种通道：空的走本机套接字，非空的把命令交回 `myshell.py exec`。
- MyShell 的令牌只在它所在的机器上被读取（见 `REMOTE` 那段远端脚本），永远不经过本机。

## 加文件时

新增运行时文件要同步四处：`scripts/build-standalone.py` 的 `PAYLOAD`、`install.sh`、`Makefile` 的 `dist` 和 `lint`、`bin/ssh-hold` 里 `unpack_embedded` 的完整性判断。

## 变更

- 2026-11-17：新增 `myshell.py`。
