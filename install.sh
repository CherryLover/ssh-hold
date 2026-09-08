#!/usr/bin/env bash
# ssh-hold 安装脚本。
#
# 在解压出来的发布包或源码目录里直接跑，就装本地这一份：
#   ./install.sh
#
# 直接从网上装最新发布版：
#   curl -fsSL https://raw.githubusercontent.com/CherryLover/ssh-hold/main/install.sh | bash
#
# 默认装到 ~/.local（bin/ 和 lib/），加 --prefix 换地方。
set -euo pipefail

REPO="CherryLover/ssh-hold"
PREFIX="${PREFIX:-$HOME/.local}"
VERSION=""
ACTION="install"
WITH_SKILL=0
# 直接指定发布包地址，跳过版本查询。CI 用它拿本地包演一遍联网安装那条路径。
RELEASE_URL="${SSH_HOLD_RELEASE_URL:-}"

die() {
  echo "install.sh: $*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
用法: ./install.sh [选项]

  --prefix 目录     安装前缀，默认 ~/.local
  --version 版本    指定要装的版本（例如 v1.1.0），只在联网安装时有意义
  --with-skill      装完顺手把用法教给本机的 Claude Code / Codex
  --uninstall       卸载已安装的文件，不动 ~/.ssh/hold 里的通道
  -h, --help        显示这段说明

装完的位置:
  <前缀>/bin/ssh-hold
  <前缀>/lib/ssh-hold/{askpass,paste.py}
  <前缀>/share/ssh-hold/SKILL.md
  <前缀>/share/man/man1/ssh-hold.1
  <前缀>/share/bash-completion/completions/ssh-hold
  <前缀>/share/zsh/site-functions/_ssh-hold

不加 --with-skill 就不会往 ~/.claude、~/.codex 里写任何东西。
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix) [[ $# -ge 2 ]] || die "--prefix 后面要跟目录"; PREFIX="$2"; shift 2 ;;
    --version) [[ $# -ge 2 ]] || die "--version 后面要跟版本号"; VERSION="$2"; shift 2 ;;
    --with-skill) WITH_SKILL=1; shift ;;
    --uninstall) ACTION="uninstall"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "未知选项: $1" ;;
  esac
done

# 通过管道跑时 BASH_SOURCE 指不到真实文件，这时只能走联网安装。
SRC=""
if [[ -z "$RELEASE_URL" && -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
  candidate="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  [[ -f "$candidate/bin/ssh-hold" ]] && SRC="$candidate"
fi

uninstall() {
  local removed=0 path
  for path in \
    "$PREFIX/bin/ssh-hold" \
    "$PREFIX/lib/ssh-hold" \
    "$PREFIX/share/ssh-hold" \
    "$PREFIX/share/man/man1/ssh-hold.1" \
    "$PREFIX/share/bash-completion/completions/ssh-hold" \
    "$PREFIX/share/zsh/site-functions/_ssh-hold"
  do
    if [[ -e "$path" ]]; then
      rm -rf "$path"
      echo "已删除 $path"
      removed=1
    fi
  done
  (( removed )) || echo "$PREFIX 下没有找到已安装的 ssh-hold。"
  echo "通道记录（~/.ssh/hold）没有动。要清掉请自己 ssh-hold stop。"
  echo "写进 ~/.claude、~/.codex 的 skill 也没动，不要了就自己删掉 skills/ssh-hold/。"
}

# 下载用的临时目录。放在全局，否则 EXIT trap 触发时变量已经出了函数作用域，
# set -u 下会直接报 unbound variable，让本来成功的安装以非 0 退出。
WORKDIR=""
cleanup() {
  [[ -n "$WORKDIR" && -d "$WORKDIR" ]] && rm -rf "$WORKDIR"
  return 0
}
trap cleanup EXIT

fetch() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$1"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- "$1"
  else
    die "需要 curl 或 wget 才能联网安装"
  fi
}

download_release() {
  local tag url
  WORKDIR="$(mktemp -d)"
  url="$RELEASE_URL"
  if [[ -z "$url" ]]; then
    tag="$VERSION"
    if [[ -z "$tag" ]]; then
      echo "正在查询最新版本 ..." >&2
      tag="$(fetch "https://api.github.com/repos/$REPO/releases/latest" \
        | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"
      [[ -n "$tag" ]] || die "查不到最新版本，请用 --version 指定，或检查网络"
    fi
    url="https://github.com/$REPO/releases/download/$tag/ssh-hold-${tag#v}.tar.gz"
  fi
  echo "正在下载 $url ..." >&2
  fetch "$url" >"$WORKDIR/pkg.tar.gz" || die "下载失败: $url"
  tar -xzf "$WORKDIR/pkg.tar.gz" -C "$WORKDIR" || die "解压失败，下载的文件可能不完整"
  # 包里是 ssh-hold-<版本>/bin/ssh-hold，从 WORKDIR 数下来是第 3 层。
  local found
  found="$(find "$WORKDIR" -maxdepth 3 -type f -path '*/bin/ssh-hold' | head -1)"
  [[ -n "$found" ]] || die "发布包里找不到 bin/ssh-hold"
  SRC="${found%/bin/ssh-hold}"
}

install_file() {
  local src="$1" dest="$2" mode="$3"
  [[ -f "$src" ]] || return 0
  mkdir -p "$(dirname "$dest")"
  cp "$src" "$dest"
  chmod "$mode" "$dest"
}

if [[ "$ACTION" == "uninstall" ]]; then
  uninstall
  exit 0
fi

[[ -n "$SRC" ]] || download_release

# 覆盖安装前先备份旧的可执行文件，出问题还能换回去。
if [[ -f "$PREFIX/bin/ssh-hold" ]]; then
  backup="$PREFIX/bin/ssh-hold.bak.$(date "+%Y%m%d%H%M%S")"
  cp "$PREFIX/bin/ssh-hold" "$backup"
  echo "旧版本已备份到 $backup"
fi

install_file "$SRC/bin/ssh-hold" "$PREFIX/bin/ssh-hold" 755
install_file "$SRC/lib/askpass" "$PREFIX/lib/ssh-hold/askpass" 755
install_file "$SRC/lib/paste.py" "$PREFIX/lib/ssh-hold/paste.py" 644
install_file "$SRC/skill/SKILL.md" "$PREFIX/share/ssh-hold/SKILL.md" 644
install_file "$SRC/man/ssh-hold.1" "$PREFIX/share/man/man1/ssh-hold.1" 644
install_file "$SRC/completions/ssh-hold.bash" "$PREFIX/share/bash-completion/completions/ssh-hold" 644
install_file "$SRC/completions/_ssh-hold" "$PREFIX/share/zsh/site-functions/_ssh-hold" 644

echo
echo "装好了：$PREFIX/bin/ssh-hold"
"$PREFIX/bin/ssh-hold" version

if (( WITH_SKILL )); then
  echo
  "$PREFIX/bin/ssh-hold" skill install
else
  echo
  echo "要把用法教给 Claude Code / Codex，跑一下："
  echo "  $PREFIX/bin/ssh-hold skill install"
fi

case ":$PATH:" in
  *":$PREFIX/bin:"*) ;;
  *)
    echo
    echo "注意：$PREFIX/bin 不在 PATH 里。把下面这行加进 ~/.zshrc 或 ~/.bashrc："
    echo "  export PATH=\"$PREFIX/bin:\$PATH\""
    ;;
esac
