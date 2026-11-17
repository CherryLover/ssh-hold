# 更新记录

## 1.2.0 — 2026-11-17

能在通道上直接传文件了，另外修掉了通道记录损坏时的几处问题。

### 新增 `ssh-hold upload` / `ssh-hold download`

```bash
ssh-hold upload web ./app.tar.gz /tmp/
ssh-hold download web /var/log/nginx/error.log ./
```

- 最后一个参数是目的地，前面的都是源；文件、目录、多个源都行，别名 `put` / `get`
- 底下是复用同一个套接字的 `scp`，不再认证，退出码原样传回。不做断点续传，要的话用 `rsync` 复用套接字
- 通道名必须写，不像 `run` 那样只有一条时可以省——省了就得把第一个路径猜成名字
- 相对的本机路径会补上 `./`，文件名里带冒号或以短横线开头也不会被 `scp` 误读

### 修复

- **记录损坏的通道关不掉**：`stop` 会先去读 `meta`，读不出来就直接退出，而那条报错给的建议恰恰是「`stop` 后重开」。现在 `stop` 不看记录内容
- **`start -n ..` 没被拦住**：通道名校验放过了 `.` 和 `..`，套接字和记录会写到通道目录外面。现在全是点的名字一律拒绝
- **带路径的名字能绕过 `list`**：认不认得一个名字原来是拿它拼路径探文件，`run ../x/web` 这种写法探得到。现在只认 `list` 里有的
- **损坏的记录会冒用上一条通道的地址**：`list` 逐条读记录时变量没清，后一条读不出目标时沿用了前一条的。现在每次读之前先清空
- **一条坏记录让 `list` 半路退出**：排在它后面的通道全都列不出来。现在只把这条标成「记录: 坏了」，其余照常列；`run`、`shell`、传文件碰到坏记录仍然直接停下
- `shell` 的断线提示还是「请拿新密码重新 start」，对证书通道不对；`run`、`shell`、传文件现在共用同一句
- README 常见报错表里两条报错原文和程序实际输出对不上，已对齐

### 安装

- **可以用 Homebrew 装了**：`brew install cherrylover/tap/ssh-hold`。Formula 在
  [CherryLover/homebrew-tap](https://github.com/CherryLover/homebrew-tap)，装完带 man 手册和
  bash / zsh 补全。tap 里有个定时任务每天自动把 formula 对齐到最新 Release，不需要手工改
  版本号和校验和。程序本身没改动——它本来就是按可执行文件的位置找运行库，Homebrew 的
  Cellar 布局直接就能用。

## 1.1.0 — 2026-09-08

把「教 AI 工具怎么用它」这件事做进了命令本身。

### 新增 `ssh-hold skill`

```bash
ssh-hold skill install          # 按本机装了哪个自动挑
ssh-hold skill install --codex  # 只装给 Codex
ssh-hold skill path             # 只看会写到哪儿
ssh-hold skill show             # 打印内容
```

- `SKILL.md` 现在跟着程序一起发布，装到 `<前缀>/share/ssh-hold/SKILL.md`，单文件版则内嵌
- 不写目标选项时看本机装了什么：`~/.claude` 在就装给 Claude Code，`~/.codex` 在就装给 Codex，两个都在就都装。两边是同一种格式，一份文件通吃
- `--dir` 可以装到任意 skills 根目录，比如某个项目自己的 `.claude/skills`
- 重复跑安全：内容一样什么都不做；手改过的版本先备份成 `SKILL.md.bak.<时间戳>` 再覆盖
- `install.sh --with-skill` 装完顺手写出去。不加这个参数，安装过程绝不碰 `~/.claude` 和 `~/.codex`
- `ssh-hold version` 多打一行技能文件路径

### 文档重新定位

之前的 README、SKILL.md 和 man 手册都把「堡垒机一次性密码」当成主线来写——光 README 里「跳板机」就出现了 11 次，而 VPS、JumpServer 一次都没提。这跟工具实际的样子不符：它就是个复用 SSH 连接的工具，最常见的用法是连自己的 VPS，或者把一条已认证的连接交给 AI Agent；一次性密码只是「重连不了」的极端个例，`paste` 也只是认 JumpServer 那一种复制格式的小便利。

- README 改成先讲复用连接本身，再按「交给 AI Agent / 管多台机器 / 重连代价高」三种场合展开
- 例子从 `跳板机地址:2222` 换成普通 VPS，通道名从 `us-1` 换成 `web`
- `paste` 明确写成 JumpServer 专用的可选便利，并注明用不上可以忽略
- SKILL.md 开头改成告诉 AI「现成通道就是钥匙，别去要用户的密码」，并说明什么时候才该用 `paste`
- 命令行文案跟着改：`--password-stdin` 的说明不再是「给我用时用这个」，交互提示从「请输入一次性密码」改成「请输入密码」
- 断线报错原来写死「一次性密码无法重连」，对证书通道是错的，改成分别说明两种通道怎么恢复

### SKILL.md 内容更新

- **补上了 `paste`**：之前整个命令都没写进去，用户说"信息复制好了"时 AI 只能退回去手敲
- **删掉过时的 sshpass**：早就改成走 `SSH_ASKPASS` 了，文档里还留着"缺依赖就 brew install sshpass"
- 补上 `--verify-password` 会等输入、不能在工具调用里跑的警告
- 报错对照表补上剪贴板解析失败、凭据过期、运行库找不到几种情况
- 不再写死"脚本在 `~/.local/bin/ssh-hold`"，改成让 AI 用 `ssh-hold version` 自己看

## 1.0.1 — 2026-09-08

修掉 1.0.0 联网安装路径上的两个问题。从发布包本地安装不受影响。

- **`curl | bash` 装完会以退出码 1 结束**：清理临时目录的 EXIT trap 引用了函数内的局部变量，触发时变量已出作用域，`set -u` 下报 unbound variable。东西其实装好了，但退出码是错的，放进自动化脚本里会被当成失败。改成全局变量，临时目录也能正常清掉
- **联网安装找不到发布包内容**：按目录深度 2 找 `bin/ssh-hold`，但包里实际是 `ssh-hold-<版本>/bin/ssh-hold`，从临时目录数下来是第 3 层，永远找不到
- 仓库里的 `install.sh` 补上可执行权限，README 写的 `./install.sh` 现在能直接跑
- 新增 `SSH_HOLD_RELEASE_URL`，可以直接指定发布包地址跳过版本查询；CI 用它拿本地包把联网安装那条路径完整演一遍，这类问题以后能自动发现

## 1.0.0 — 2026-09-08

第一个正式发布版本。此前 `ssh-hold` 一直是本机 `~/.local/bin` 下的一个脚本，这次整理成项目、开源，并提供打好的发布包。

功能上和之前的本机版本一致，改动集中在打包和安装：

- **单文件版**：`askpass` 和 `paste.py` 内嵌进脚本，下载一个文件丢进 PATH 就能用，真正需要时才写进 `~/.cache/ssh-hold/`
- **发布包**：`tar.gz` 里含可执行文件、运行库、man 手册、bash / zsh 补全和安装脚本，附 SHA256 校验和
- **安装脚本**：`install.sh` 支持从本地目录装，也支持 `curl | bash` 联网装最新版；覆盖安装会先备份旧的可执行文件；`--uninstall` 卸载时不动已撑开的通道
- **运行库路径不再写死**：原来固定读 `~/.local/lib/ssh-hold/`，现在跟随可执行文件所在的安装位置，也可以用 `SSH_HOLD_LIB` 指定。装到 `/usr/local` 或任意前缀都能正常工作
- **新增 `ssh-hold version`**：显示版本号、程序路径、运行库路径和通道目录
- **man 手册和补全**：`man ssh-hold`；bash / zsh 下补全子命令、选项，以及已经撑开的通道名
- **测试跟着仓库走**：原来测试写死 `~/.local/bin/ssh-hold`，现在默认跑当前这份代码，CI 在 macOS 和 Linux 上都跑一遍

### 之前的本机改动（未单独发版）

- 2026-09-08：新增 `paste`，直接读剪贴板里的堡垒机连接信息撑开通道；密码改走 `SSH_ASKPASS`，不再依赖 `sshpass`
- 2026-08-15：通道名写错时直接报错并列出现有通道，不再退回去挑另一条执行
