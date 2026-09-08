# ssh-hold

把一条 SSH 连接撑住，之后所有命令都复用它，不用再输一次密码。

跳板机发的一次性密码只能用一次，登进去开第二个终端就没辙了。`ssh-hold` 在第一次登录时把连接留在后台，后面执行命令、传文件、开交互终端全都走这条已经开着的通道，不再重新认证。同样的机制也适合把一条连接交给自动化脚本或者 AI Agent 用，不用反复把凭据递出去。

底层就是 OpenSSH 自带的 ControlMaster，没有自研协议，也不常驻守护进程。密码全程不落盘。

```
$ ssh-hold start -n us-1 -p 2222 ubuntu@跳板机地址
请输入一次性密码（输入时不会显示）：

通道已撑开：us-1
  目标: 跳板机地址:2222
  时间: 2026-09-08 21:30:11

$ ssh-hold run us-1 -- 'df -h | head -3'
Filesystem      Size  Used Avail Use% Mounted on
/dev/root        58G   12G   47G  20% /
tmpfs           3.9G     0  3.9G   0% /dev/shm

$ ssh-hold list
SSH 通道：
  us-1
    目标: ubuntu@跳板机地址:2222
    开通: 2026-09-08 21:30:11
    通道: 畅通
    保活: 在跑 (pid 31785)
    远端: ubuntu@ip-172-26-10-104
```

## 安装

联网装最新发布版：

```bash
curl -fsSL https://raw.githubusercontent.com/CherryLover/ssh-hold/main/install.sh | bash
```

默认装到 `~/.local`，换地方加 `--prefix`：

```bash
curl -fsSL https://raw.githubusercontent.com/CherryLover/ssh-hold/main/install.sh | bash -s -- --prefix /usr/local
```

或者从 [Releases](https://github.com/CherryLover/ssh-hold/releases) 下发布包自己装：

```bash
tar -xzf ssh-hold-1.0.0.tar.gz
cd ssh-hold-1.0.0
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

卸载：`./install.sh --uninstall`（不会动 `~/.ssh/hold` 里已经撑开的通道）。

### 依赖

- `bash`（3.2 起，macOS 自带的就行）和 OpenSSH 客户端
- `python3`：只有 `ssh-hold paste` 用得到
- 不需要 `sshpass`。密码通过 `SSH_ASKPASS` 直接交给 ssh，不匹配终端输出

macOS 和 Linux 都能跑，`paste` 依赖 `pbpaste`，目前只支持 macOS。

## 怎么用

### 撑开通道

密码登录（跳板机、一次性密码）。默认不会先试本机密钥，免得把跳板机的尝试次数用光：

```bash
ssh-hold start -n us-1 -p 2222 ubuntu@跳板机地址
```

给脚本或 Agent 调用时，密码走标准输入，不会出现在命令行参数里：

```bash
printf '%s\n' '一次性密码' | ssh-hold start -n us-1 -p 2222 --password-stdin ubuntu@跳板机地址
```

证书登录，加 `-i` 就自动切成密钥方式：

```bash
ssh-hold start -n prod -i ~/keys/prod.pem ubuntu@1.2.3.4
```

跳板机地址常变、主机指纹对不上时加 `--insecure` 跳过指纹校验，仅限临时场景。

### 从剪贴板直接开（macOS）

堡垒机页面上复制出来的那段连接信息，可以不用手敲：

```bash
ssh-hold paste
```

它认「名称 / 主机 / 端口 / 用户名 / 密码 / 协议 / 过期时间」这几个字段，制表符、空格、中英文冒号分隔都行，过期的直接拒绝。通道名从「名称」里生成，带上资产 IP，免得几台名字相近的机器混在一起。

不确定解析对不对，先 `ssh-hold paste --check` 看一眼（会显示明文密码，别截图）。怀疑密码不对，用 `ssh-hold paste --verify-password` 跟手动输入的比一比，全程本地比较，不联网也不显示内容。

### 在通道上干活

```bash
ssh-hold run us-1 -- uname -a
ssh-hold run us-1 -- 'ps aux | head -20'
ssh-hold shell us-1
```

远端命令写在 `--` 后面。有空格、管道、重定向的整条加单引号，否则会被本机 shell 先吃掉。远端的退出码会原样传回来，可以直接做条件判断。

传文件没有专门的子命令，让 `scp` / `rsync` 复用同一个套接字就行，同样不用再认证：

```bash
scp -o ControlPath="$HOME/.ssh/hold/us-1/sock" -o ControlMaster=no \
    本地文件 ubuntu@1.2.3.4:/tmp/

rsync -avz -e "ssh -o ControlPath=$HOME/.ssh/hold/us-1/sock -o ControlMaster=no" \
    本地目录/ ubuntu@1.2.3.4:/tmp/目录/
```

### 看和关

```bash
ssh-hold list          # 所有通道，含是否畅通、保活状态、远端到底是哪台
ssh-hold status us-1   # 只看一条
ssh-hold stop us-1     # 断开并删掉记录
```

密码通道关掉往往就再也开不回来了（一次性密码已作废），`stop` 之前想清楚。

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
| 关闭 | `ssh-hold stop 名字` |
| 版本和路径 | `ssh-hold version` |

完整选项见 `ssh-hold --help` 或 `man ssh-hold`。

## 设计上的几个选择

**名字写错就停下，不猜。** 写了通道名却对不上，直接报错并列出现有通道，绝不退回去挑另一条执行——猜错等于在别的机器上干活。开着多条通道时省略名字同样报错，只有恰好一条时才允许省略。

**密码不落盘，也不进命令行。** `--password-stdin` 从标准输入读，再通过 `SSH_ASKPASS` 交给 ssh。不用 `sshpass`，不去匹配终端输出，`ps` 里看不到密码，`meta` 文件里也不存。

**密码里的空白当数据看。** 剪贴板解析时不会悄悄裁掉密码的首尾空白，而是明确告诉你去掉了几个字符；确实需要保留就加 `--keep-password-spaces`。

**保活会放弃。** 后台每 20 秒在远端跑一次空命令，防止被按空闲踢掉。连续失败 3 次就停下并记进 `keepalive.log`，不做无意义的重连——一次性密码本来也重连不了。

## 状态和文件

通道记录在 `~/.ssh/hold/<名字>/`：

- `sock` —— ControlMaster 复用套接字
- `meta` —— 目标地址、端口、开通时间、认证方式，不含密码
- `keepalive.log` —— 保活日志，通道异常先看这里

环境变量 `SSH_HOLD_DIR` 换通道目录，`SSH_HOLD_LIB` 换运行库目录（一般不用管，会自动跟随可执行文件所在的那份安装）。

## 常见报错

| 看到 | 意思 | 怎么办 |
|---|---|---|
| `通道 xxx 已经断了。一次性密码无法重连` | 通道掉了 | 密码通道要拿新密码重新 `start`；证书通道用原来的 `-i` 再 `start` |
| `没有名为 xxx 的通道，不执行。现有: ...` | 名字写错，已经拦住 | 从 `list` 里照抄名字重跑 |
| `通道名后面要加 --` | 漏了 `--` | `ssh-hold run 名字 -- 命令` |
| `有多条通道，请写名字` | 省略了名字 | 补上名字 |
| `通道没撑起来。密码错了、过期了，或者跳板机拒绝了连接。` | start 失败 | 确认密码是否还有效、地址端口对不对；指纹问题加 `--insecure` |
| `找不到运行库（askpass / paste.py）` | 安装不完整 | 重新装一遍，或用 `SSH_HOLD_LIB` 指定 lib 目录 |
| `密钥文件不存在` / `Permissions too open` | 证书路径或权限 | 核对路径；`chmod 600 证书.pem` |

其他容易踩的：

- 已经撑开的通道，密码过期通常还能继续用，一旦断开就没法自动重连
- 跳板机若设了最长会话时间，到点还是会被踢，这个挡不住
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

打标签 `v*` 推上去，GitHub Actions 会自动跑测试、打包、发 Release。

## 许可

MIT
