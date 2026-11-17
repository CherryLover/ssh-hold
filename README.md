# ssh-hold

[![CI](https://github.com/CherryLover/ssh-hold/actions/workflows/ci.yml/badge.svg)](https://github.com/CherryLover/ssh-hold/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/CherryLover/ssh-hold)](https://github.com/CherryLover/ssh-hold/releases/latest)
[![License](https://img.shields.io/github/license/CherryLover/ssh-hold)](LICENSE)

连一次服务器，把这条连接留着，之后所有命令都复用它，不用再认证第二次。

```
$ ssh-hold start -n web -i ~/keys/vps.pem ubuntu@1.2.3.4

通道已撑开：web
  目标: ubuntu@1.2.3.4:22
  时间: 2026-09-08 21:30:11

$ ssh-hold run web -- 'df -h / | tail -1'
/dev/sda1        96G   52G   45G  54% /

$ ssh-hold run web -- 'systemctl is-active nginx'
active

$ ssh-hold list
SSH 通道：
  web
    目标: ubuntu@1.2.3.4:22
    开通: 2026-09-08 21:30:11
    通道: 畅通
    保活: 在跑 (pid 31785)
    远端: ubuntu@vps-tokyo-01
```

底层就是 OpenSSH 自带的 ControlMaster，没有自研协议，也不常驻守护进程。密码全程不落盘。

## 什么时候用得上

**把一条已经认证好的连接交给 AI Agent。** 这是它最初的动机。你自己登一次，之后 Claude Code 或 Codex 就能在这条通道上查日志、看进程、改配置，全程不需要拿到你的密码或私钥。跑一条 [`ssh-hold skill install`](#教给-claude-code--codex) 就能把用法教给它们。

**连着的服务器多、来回切。** 每台撑开一条，`ssh-hold run 名字 -- 命令` 直接打过去，不用记地址端口，也不用每次等重新握手。

**重连代价高或者根本不可能的时候。** 比如堡垒机发的一次性密码，用过一次就作废，普通做法连第二个终端都开不了。这类场景 `ssh-hold` 是刚需，但它并不是只为这个做的。

## 安装

macOS / Linuxbrew：

```bash
brew install cherrylover/tap/ssh-hold
```

不想用 Homebrew 的话，一行命令装最新发布版：

```bash
curl -fsSL https://raw.githubusercontent.com/CherryLover/ssh-hold/main/install.sh | bash
```

默认装到 `~/.local`，换地方加 `--prefix`：

```bash
curl -fsSL https://raw.githubusercontent.com/CherryLover/ssh-hold/main/install.sh | bash -s -- --prefix /usr/local
```

或者从 [Releases](https://github.com/CherryLover/ssh-hold/releases) 下发布包自己装：

```bash
tar -xzf ssh-hold-<版本>.tar.gz
cd ssh-hold-<版本>
./install.sh
```

只想要一个文件、丢进 PATH 就能用的，下 Release 里的 `ssh-hold` 单文件版：

```bash
curl -fsSLo ~/.local/bin/ssh-hold \
  https://github.com/CherryLover/ssh-hold/releases/latest/download/ssh-hold
chmod +x ~/.local/bin/ssh-hold
```

单文件版把 `askpass` 和 `paste.py` 内嵌在脚本里，真正用到时才写进 `~/.cache/ssh-hold/`。

装完确认一下：

```bash
ssh-hold version
```

卸载：`brew uninstall ssh-hold`，或者脚本装的用 `./install.sh --uninstall`。两种都不会动 `~/.ssh/hold` 里已经撑开的通道，也不会删掉写进 `~/.claude`、`~/.codex` 的 skill。

## 教给 Claude Code / Codex

这个工具最初就是为了让 AI Agent 能安全地用一条已认证的连接干活。跑一条命令，就把用法写进本机 AI 编程工具的 skills 目录：

```bash
ssh-hold skill install
```

它自己看本机装了什么：`~/.claude` 在就装给 Claude Code，`~/.codex` 在就装给 Codex，两个都在就都装。两边用的是同一种 `SKILL.md` 格式，一份文件通吃。

```
$ ssh-hold skill install
已写入 /Users/you/.claude/skills/ssh-hold/SKILL.md
已写入 /Users/you/.codex/skills/ssh-hold/SKILL.md

新开一个会话才会加载到。
```

想先看看会写到哪儿，或者看看内容：

```bash
ssh-hold skill path     # 只打印路径，不动文件
ssh-hold skill show     # 把 SKILL.md 打到标准输出
```

只装一个，或者装到别处：

```bash
ssh-hold skill install --claude
ssh-hold skill install --codex
ssh-hold skill install --dir ~/某项目/.claude/skills
```

重复跑是安全的：内容一样就什么都不做；你手改过的版本会先备份成 `SKILL.md.bak.<时间戳>` 再覆盖。装 ssh-hold 时加 `--with-skill` 可以一步到位，不加就绝不往 `~/.claude`、`~/.codex` 里写任何东西。

这份 skill 教的不只是命令语法，还有几条容易踩坑的规矩：通道名写错必须停下不能猜、哪些命令会在非交互场景里卡死、密码该从哪来不该从哪来。

### 依赖

- `bash`（3.2 起，macOS 自带的就行）和 OpenSSH 客户端
- `python3`：只有 `ssh-hold paste` 用得到
- 不需要 `sshpass`。密码通过 `SSH_ASKPASS` 直接交给 ssh，不匹配终端输出

macOS 和 Linux 都能跑，`paste` 依赖 `pbpaste`，目前只支持 macOS。

## 怎么用

### 撑开通道

证书登录，加 `-i` 就自动切成密钥方式，日常连自己的 VPS 基本都走这条：

```bash
ssh-hold start -n web -i ~/keys/vps.pem ubuntu@1.2.3.4
```

密码登录。默认不会先试本机密钥，免得在只认密码的服务器上把尝试次数用光：

```bash
ssh-hold start -n web -p 2222 ubuntu@1.2.3.4
```

给脚本或 Agent 调用时，密码走标准输入，不会出现在命令行参数里：

```bash
printf '%s\n' '密码' | ssh-hold start -n web --password-stdin ubuntu@1.2.3.4
```

地址经常变、主机指纹对不上时加 `--insecure` 跳过指纹校验，仅限临时场景。

多台机器同时撑开，用 `-n` 起不同名字区分。不写 `-n` 默认叫 `default`，不写 `-p` 默认 22。

### 从剪贴板直接开（可选，macOS）

如果你的服务器挂在 [JumpServer](https://github.com/jumpserver/jumpserver) 后面，它的资产页面会给你一段可以整段复制的连接信息。`ssh-hold paste` 认这个格式，省得手敲一遍：

```bash
ssh-hold paste
```

它读「名称 / 主机 / 端口 / 用户名 / 密码 / 协议 / 过期时间」这几个字段，制表符、空格、中英文冒号分隔都行，过期的直接拒绝。通道名从「名称」里生成并带上资产 IP，免得几台名字相近的机器混在一起。

不确定解析对不对，先 `ssh-hold paste --check` 看一眼（会显示明文密码，别截图）。怀疑密码不对，用 `ssh-hold paste --verify-password` 跟手动输入的比一比，全程本地比较，不联网也不显示内容。

这就是个针对某一种复制格式的小便利，用不上完全可以忽略——直接 `start` 一样能连。

### 在通道上干活

```bash
ssh-hold run web -- uname -a
ssh-hold run web -- 'ps aux | head -20'
ssh-hold shell web
```

远端命令写在 `--` 后面。有空格、管道、重定向的整条加单引号，否则会被本机 shell 先吃掉。远端的退出码会原样传回来，可以直接做条件判断。

### 传文件

```bash
ssh-hold upload web ./app.tar.gz /tmp/                 # 本机 → 远端
ssh-hold upload web ./dist ./nginx.conf /srv/app/      # 多个源、目录都行
ssh-hold download web /var/log/nginx/error.log ./      # 远端 → 本机
ssh-hold download web /etc/nginx /srv/app/.env ./备份/
```

最后一个参数是目的地，前面的都是源；目录会整个传过去。通道名必须写，哪怕只开着一条——省略的话第一个路径就得被猜成名字，这个工具不猜。底下是复用同一个套接字的 `scp`，不用再认证，退出码原样传回；没有断点续传，传一半断了就重来。

要增量同步或断点续传，让 `rsync` 复用同一个套接字：

```bash
rsync -avz --partial -e "ssh -o ControlPath=$HOME/.ssh/hold/web/sock -o ControlMaster=no" \
    本地目录/ ubuntu@1.2.3.4:/tmp/目录/
```

### 看和关

```bash
ssh-hold list          # 所有通道，含是否畅通、保活状态、远端到底是哪台
ssh-hold status web   # 只看一条
ssh-hold stop web     # 断开并删掉记录
```

证书通道随时可以再 `start` 回来；密码通道要重新拿到密码才行，如果那是一次性凭据就彻底开不回来了，`stop` 之前想清楚。

## 命令一览

| 目的 | 命令 |
|---|---|
| 列出所有通道 | `ssh-hold list` |
| 只看一条 | `ssh-hold status 名字` |
| 密码撑开 | `ssh-hold start -n 名字 [-p 端口] [--insecure] 用户@地址` |
| 密码走 stdin | `printf '%s\n' '密码' \| ssh-hold start -n 名字 --password-stdin 用户@地址` |
| 证书撑开 | `ssh-hold start -n 名字 -i 证书.pem 用户@地址` |
| 剪贴板撑开 | `ssh-hold paste [-n 名字] [--check]` |
| 执行命令 | `ssh-hold run 名字 -- '命令'` |
| 交互终端 | `ssh-hold shell 名字` |
| 上传 | `ssh-hold upload 名字 本地路径... 远端路径` |
| 下载 | `ssh-hold download 名字 远端路径... 本地路径` |
| 关闭 | `ssh-hold stop 名字` |
| 教给 AI 工具 | `ssh-hold skill install` |
| 版本和路径 | `ssh-hold version` |

完整选项见 `ssh-hold --help` 或 `man ssh-hold`。

## 设计上的几个选择

**名字写错就停下，不猜。** 写了通道名却对不上，直接报错并列出现有通道，绝不退回去挑另一条执行——猜错等于在别的机器上干活。开着多条通道时省略名字同样报错，只有恰好一条时才允许省略。

**密码不落盘，也不进命令行。** `--password-stdin` 从标准输入读，再通过 `SSH_ASKPASS` 交给 ssh。不用 `sshpass`，不去匹配终端输出，`ps` 里看不到密码，`meta` 文件里也不存。

**密码里的空白当数据看。** 剪贴板解析时不会悄悄裁掉密码的首尾空白，而是明确告诉你去掉了几个字符；确实需要保留就加 `--keep-password-spaces`。

**保活会放弃。** 后台每 20 秒在远端跑一次空命令，防止被按空闲踢掉。连续失败 3 次就停下并记进 `keepalive.log`，不自己偷偷重连——重连要用哪套凭据、还能不能用，只有你知道。

## 状态和文件

通道记录在 `~/.ssh/hold/<名字>/`：

- `sock` —— ControlMaster 复用套接字
- `meta` —— 目标地址、端口、开通时间、认证方式，不含密码
- `keepalive.log` —— 保活日志，通道异常先看这里

环境变量 `SSH_HOLD_DIR` 换通道目录，`SSH_HOLD_LIB` 换运行库目录（一般不用管，会自动跟随可执行文件所在的那份安装）。

## 常见报错

| 看到 | 意思 | 怎么办 |
|---|---|---|
| `通道 xxx 已经断了，不会自动重连` | 通道掉了 | 证书通道用原来的 `-i` 再 `start`；密码通道要拿新密码重新 `start` |
| `没有名为 xxx 的通道，不执行。现有: ...` | 名字写错，已经拦住 | 从 `list` 里照抄名字重跑 |
| `通道名后面要加 --` | 漏了 `--` | `ssh-hold run 名字 -- 命令` |
| `有多条通道，请写名字` | 省略了名字 | 补上名字 |
| `用法: ssh-hold upload 名字 源路径... 目的路径` | 传文件时漏了通道名或目的地 | 名字、源、目的三样都要写 |
| `通道 xxx 的记录坏了`，或 `list` 里显示 `记录: 坏了` | `meta` 文件损坏 | `ssh-hold stop xxx` 清掉再重开 |
| `通道没撑起来。密码或密钥不对、凭据过期了，或者对方拒绝了连接。` | start 失败 | 确认凭据是否还有效、地址端口对不对；指纹问题加 `--insecure` |
| `找不到运行库（askpass / paste.py）` | 安装不完整 | 重新装一遍，或用 `SSH_HOLD_LIB` 指定 lib 目录 |
| `密钥文件不存在` / `Permissions too open` | 证书路径或权限 | 核对路径；`chmod 600 证书.pem` |

其他容易踩的：

- 已经撑开的通道，密码过期通常还能继续用，一旦断开就没法自动重连
- 服务器或堡垒机若设了最长会话时间，到点还是会被踢，这个挡不住
- 本机重启、长时间休眠、切网络之后，先 `list` 看通道还在不在，别直接 `run`
- 远端敲 `exit` 只是退出那次登录，不会关掉通道
- 非交互场景（脚本、Agent）别跑 `shell`、不带 `--password-stdin` 的 `start`、远端的 `top` / `vim` / `less`，这些都会一直等输入

## 开发

```bash
make test        # 单元测试，不联网、不碰真实服务器
make test-wire   # 本地回环起一个 SSH 服务端，验证密码真的原样送到了对端（需要 uv）
make lint        # shellcheck + 语法检查
make dist        # 打发布包
make install     # 装到 ~/.local
```

`make test-wire` 用 paramiko 在 127.0.0.1 上起一个假的 SSH 服务端，跑完整条 `paste` → `start --password-stdin` → `run` 链路，断言服务端收到的密码和剪贴板里的完全一致，且密码没有出现在任何输出里。带引号、反斜杠、首尾空格的密码都在用例里。

`test_cli` 把 `ssh` 和 `scp` 换成替身：假 `ssh` 让记录在案的通道都算畅通，假 `scp` 只记下收到的参数。验的是「挑的是哪条通道、让 scp 干了什么」，以及记录损坏、名字非法这些边角。

`skill` 的用例在一个临时 HOME 里摆出 `.claude` / `.codex` 目录，验证自动识别、`--dir`、备份和幂等，不会碰你真实的配置。

仓库结构：`bin/` 可执行文件，`lib/` 运行时依赖（askpass、paste.py），`skill/` 发布出去的 SKILL.md，`man/`、`completions/` 手册和补全，`scripts/` 单文件版构建。

打标签 `v*` 推上去，GitHub Actions 会自动跑测试、打包、发 Release。

## 许可

MIT
