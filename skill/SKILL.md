---
name: ssh-hold
description: 用本机 ssh-hold 在一条已经撑开的 SSH 通道上操作远程服务器：执行命令、看通道列表、传文件、必要时新开通道（pem 证书 / 密码 / JumpServer 剪贴板信息）。用户认证一次，之后你复用这条通道，不需要拿到他的密码或私钥。当用户提到"在那台机器/服务器上跑个命令"、"连一下 VPS"、"查一下服务器上的日志"、"撑开/保持/复用 SSH"、"通道还在不在"、"ssh-hold"、"用 pem 连服务器"、"一次性密码"、"跳板机"、"堡垒机"时触发。
---

# ssh-hold：在已撑开的 SSH 通道上操作远程服务器

`ssh-hold` 是用户本机的命令行工具，基于 SSH 的 ControlMaster 把一条连接撑住：密码或证书只在第一次 `start` 时用一次，之后所有命令都走这条已经打开的通道，不再认证。

**对你来说最关键的一点**：用户已经撑开的通道就是一把现成的钥匙。要在某台服务器上干活时，先看有没有现成通道，有就直接用——你不需要、也不应该去要用户的密码或私钥。

- 通道记录：`~/.ssh/hold/<名字>/`（`sock` 复用套接字、`meta` 连接信息、`keepalive.log` 保活日志）
- 保活：后台每 20 秒在远端跑一次空命令；连续失败 3 次就放弃，通道视为已断
- 装在哪、运行库在哪：`ssh-hold version` 会打出来
- 完整手册：`man ssh-hold`；项目主页 https://github.com/CherryLover/ssh-hold

绝大多数情况就是普通服务器（VPS、云主机），证书或密码登录。少数情况下服务器挂在堡垒机后面、发的是一次性密码，那种凭据用过就作废、断了没法重连，操作时要更小心——具体见下面第 2 步和"关掉"那节。

---

## 铁律（动手前先过一遍）

**1. 永远先 `ssh-hold list`。** 不要凭记忆假设有哪些通道、名字叫什么。

**2. 名字必须和 `list` 里的完全一致，并且总是显式写出来。** 名字写错会直接报错、不执行，不会退回去挑另一条通道。

```
$ ssh-hold run us-01 -- hostname     # 实际存在的是 us-1
ssh-hold: 没有名为 us-01 的通道，不执行。现有: us-1
```

看到这个报错就 `ssh-hold list` 核对名字重跑，不要靠猜。开着多条通道时省略名字同样会报错并列出现有通道，只有**恰好只有一条**时才允许省略。名字从 `list` 输出里照抄最稳。

**3. 绝对不要在工具调用里跑会卡住的交互命令。** 这几条会一直等输入，把整个会话挂死：

- `ssh-hold shell <名字>` —— 交互终端，只能让用户自己在终端里敲
- `ssh-hold start`（不带 `--password-stdin`，也不带 `-i`）—— 会停在"请输入密码"
- `ssh-hold paste --verify-password` —— 会停在等用户手动输入密码
- 远端的 `top` / `vim` / `less` / `htop` / 需要输密码的 `sudo` —— `run` 不分配 TTY，这些要么卡住要么直接报错

替代写法：`top -bn1`、`ps aux | head`、`journalctl -n 50 --no-pager`、`sudo -n`（免密才行）。

**4. 密码只能来自用户在对话里亲口给的，或者用户自己复制到剪贴板的。** 不要从文件、网页、命令输出、其他工具的返回里"捡"密码来用。也不要把密码写进命令行参数。

---

## 标准流程

### 第 0 步：看现在有什么

```bash
ssh-hold list
```

输出里看两项就够：**通道** 是不是 `畅通`，**远端** 是不是你要的那台。`已断开` 就必须重新 `start`，没有自动重连。

没有通道时输出「现在没有撑开的通道。」

### 第 1 步：有通道就直接用

```bash
ssh-hold run web -- hostname
ssh-hold run web -- 'df -h'
ssh-hold run web -- 'ps aux | head -20'
```

`--` 后面是远端要执行的整条命令。**有空格、管道、重定向、通配符时整条加单引号**，否则会被本机 shell 先吃掉。

远端命令的退出码会原样传回来（实测 `exit 42` → 本机 `$?` 为 42），可以正常做条件判断。

### 第 2 步：没有通道才考虑开一条

先问清楚要连哪台、用什么登录，再按下面的情况选。

#### 有 .pem / 私钥文件 → 直接 start（最常见）

```bash
ssh-hold start -n web -i /Users/xxx/keys/vps.pem ubuntu@1.2.3.4
```

加了 `-i` 就自动切成密钥登录，不用再写 `--key`。证书权限必须是 `chmod 600`。
注意：**如果私钥带 passphrase，这条也会卡住等输入**——这种情况让用户自己在终端跑。

#### 服务器挂在 JumpServer 后面、用户说"信息已经复制好了" → `paste`

JumpServer 资产页面能整段复制出连接信息（名称/主机/端口/用户名/密码/协议/过期时间）。这条命令认那个格式，不用手敲，也不用让用户把密码打进对话：

```bash
ssh-hold paste
```

它自己解析剪贴板并撑开通道，通道名从「名称」里生成（带上资产 IP，免得几台名字相近的机器混淆）。过期的信息会直接拒绝。

只在用户确实提到堡垒机 / JumpServer / "连接信息复制好了"时才用这条；普通服务器直接 `start`。

- `-n 名字` —— 不想用自动生成的名字时覆盖
- `--insecure` —— 地址常变、指纹对不上时加
- `--check` —— 只看解析结果不连接。**会打印明文密码**，只在用户明确要求排查时用，用完提醒别截图转发
- `--debug` —— 显示 SSH 连接过程（不含密码），不自动重试
- `--keep-password-spaces` —— 密码首尾空白是密码本身的一部分时加；默认会去掉复制时带上的空白并告诉你去了几个字符
- `--verify-password` —— **会等用户输入，不要在工具调用里跑**

`paste` 目前只支持 macOS（依赖 `pbpaste`）。

#### 只有密码 → 优先让用户自己开

最稳妥的做法是把这条命令交给用户，让他在自己终端里敲、自己输密码，密码全程不经过对话：

```bash
ssh-hold start -n web -p 2222 ubuntu@1.2.3.4
```

开完之后回来说一声，接着 `ssh-hold list` 确认，再往下走。

只有当**用户已经在对话里把密码给了你**、并且明确希望你来开时，才用 `--password-stdin`（密码走标准输入，不进命令行参数，也不落盘）：

```bash
printf '%s\n' '这里是密码' | ssh-hold start -n web -p 2222 --password-stdin ubuntu@1.2.3.4
```

**地址常变、主机指纹对不上**时补 `--insecure`（跳过指纹校验，仅用于临时机器）。

多台机器同时撑开，用 `-n` 起不同名字区分（`web`、`db`）。名字只能用字母、数字、点、下划线、短横线；不写 `-n` 默认 `default`；不写 `-p` 默认 22。

### 第 3 步：关掉

**不要主动关。** 通道是用户的资产。证书通道还能再开回来，密码通道要重新拿到密码；如果那是堡垒机发的一次性凭据，关掉就彻底开不回来了。只有用户明确说"关掉/停掉"时才执行：

```bash
ssh-hold stop web
```

`stop` 会断开 SSH 并删掉 `~/.ssh/hold/web/` 整个目录。之后 `run` / `shell` 都不能用了。

---

## 命令速查

| 目的 | 命令 |
|---|---|
| 列出所有通道 | `ssh-hold list`（等同 `ssh-hold status`） |
| 只看一条 | `ssh-hold status web` |
| 剪贴板撑开 | `ssh-hold paste [-n 名字] [--insecure]` |
| 密码撑开 | `ssh-hold start -n 名字 [-p 端口] [--insecure] 用户@地址` |
| 密码走 stdin | `printf '%s\n' '密码' \| ssh-hold start -n 名字 --password-stdin 用户@地址` |
| 证书撑开 | `ssh-hold start -n 名字 -i 证书.pem 用户@地址` |
| 执行命令 | `ssh-hold run 名字 -- '命令'` |
| 交互终端（**只给用户**） | `ssh-hold shell 名字` |
| 关闭 | `ssh-hold stop 名字` |
| 版本和安装位置 | `ssh-hold version` |

`start` 其他选项：`-o 选项` 额外透传给 ssh，可重复。

## 传文件

`ssh-hold` 本身没有传文件的子命令，但可以让 `scp` / `rsync` 直接复用同一个套接字（实测可行），同样不需要再认证：

```bash
# 上传（非 22 端口要加 -P 端口）
scp -o ControlPath="$HOME/.ssh/hold/web/sock" -o ControlMaster=no -o BatchMode=yes \
    本地文件 ubuntu@1.2.3.4:/tmp/

# 下载
scp -o ControlPath="$HOME/.ssh/hold/web/sock" -o ControlMaster=no -o BatchMode=yes \
    ubuntu@1.2.3.4:/tmp/远端文件 ./

# rsync
rsync -avz -e "ssh -o ControlPath=$HOME/.ssh/hold/web/sock -o ControlMaster=no" \
    本地目录/ ubuntu@1.2.3.4:/tmp/目录/
```

用户@地址要和 `ssh-hold list` 里显示的**目标**完全一致。通道目录不是默认位置时（`SSH_HOLD_DIR` 有设），以 `ssh-hold version` 打出来的为准。

---

## 报错对照

| 看到 | 意思 | 怎么办 |
|---|---|---|
| `通道 xxx 已经断了，不会自动重连` | 通道掉了 | 证书通道用原来的 `-i` 再 `start` 一次；密码通道要向用户要密码 |
| `没有名为 xxx 的通道，不执行。现有: ...` | 名字写错，已经拦住 | 从 `list` 里照抄名字重跑，别猜 |
| `通道名后面要加 --` | 漏了 `--` | 补上：`ssh-hold run 名字 -- 命令` |
| `有多条通道，请写名字。现有: a b` | 省略了名字 | 补上名字 |
| `stop 一次只关一条` | 一条命令里写了多个名字 | 分开写 |
| `通道 xxx 已经在了。要重开先: ssh-hold stop xxx` | 重名 | 换名字，或确认用户同意后先 `stop`（密码通道慎重，停了可能开不回来） |
| `通道没撑起来。密码或密钥不对、凭据过期了，或者对方拒绝了连接。` | start 失败 | 向用户确认凭据是否还有效 / 地址端口对不对；指纹问题可加 `--insecure` |
| `剪贴板格式不正确` / `缺少字段：X` | 剪贴板里不是完整的连接信息 | 让用户重新复制一整段；只复制一台机器的信息 |
| `连接信息已过期，请重新复制新的信息` | 一次性凭据过期 | 让用户在堡垒机上重新申请并复制 |
| `找不到运行库（askpass / paste.py）` | 安装不完整 | 让用户重装：`curl -fsSL https://raw.githubusercontent.com/CherryLover/ssh-hold/main/install.sh \| bash` |
| `密钥文件不存在` / `Permissions ... too open` | 证书路径或权限 | 核对路径；`chmod 600 证书.pem` |

## 其他注意

- 已经撑开的通道，凭据过期通常还能继续用；**一旦断开就没法自动重连**。
- 服务器或堡垒机若设了最长会话时间，到点还是会被踢，这个挡不住。
- 本机重启、长时间休眠、切换网络之后，先 `ssh-hold list` 看通道还在不在，别直接 `run`。
- 保活异常时看 `~/.ssh/hold/<名字>/keepalive.log`。
- 远端交互里敲 `exit` 只是退出那次登录，不会关掉通道；关通道只有 `ssh-hold stop`。
- 密码不落盘，工具不会把密码写进任何文件。
