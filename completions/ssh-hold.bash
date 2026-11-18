# bash completion for ssh-hold

_ssh_hold_names() {
  local base="${SSH_HOLD_DIR:-$HOME/.ssh/hold}" meta
  for meta in "$base"/*/meta; do
    [[ -f "$meta" ]] || continue
    basename "$(dirname "$meta")"
  done
}

_ssh_hold() {
  local cur prev cmd i
  cur="${COMP_WORDS[COMP_CWORD]}"
  prev="${COMP_WORDS[COMP_CWORD-1]}"

  for (( i = 1; i < COMP_CWORD; i++ )); do
    case "${COMP_WORDS[i]}" in
      -*) ;;
      *) cmd="${COMP_WORDS[i]}"; break ;;
    esac
  done

  if [[ -z "$cmd" ]]; then
    COMPREPLY=($(compgen -W "start paste run shell upload download status list stop link-myshell skill version --help --version" -- "$cur"))
    return
  fi

  case "$prev" in
    -n|--name|-p|--port|-o|--group|--tag|--pick) return ;;
    -i|--identity) COMPREPLY=($(compgen -f -- "$cur")); return ;;
    --dir) COMPREPLY=($(compgen -d -- "$cur")); return ;;
  esac

  case "$cmd" in
    start)
      [[ "$cur" == -* ]] && COMPREPLY=($(compgen -W \
        "-n --name -p --port --password-stdin --insecure --key -i --identity -o --help" -- "$cur"))
      ;;
    paste)
      [[ "$cur" == -* ]] && COMPREPLY=($(compgen -W \
        "-n --name --check --debug --verify-password --keep-password-spaces --insecure" -- "$cur"))
      ;;
    link-myshell)
      [[ "$cur" == -* ]] && COMPREPLY=($(compgen -W \
        "-n --name -p --port -i --identity --password-stdin --insecure --group --tag --pick --help" -- "$cur"))
      ;;
    skill)
      if [[ "$cur" == -* ]]; then
        COMPREPLY=($(compgen -W "--claude --codex --dir --help" -- "$cur"))
      else
        COMPREPLY=($(compgen -W "install path show" -- "$cur"))
      fi
      ;;
    upload|put|download|get)
      # 紧跟在子命令后面的是通道名，再往后都是路径。
      if [[ "$prev" == "$cmd" ]]; then
        COMPREPLY=($(compgen -W "$(_ssh_hold_names)" -- "$cur"))
      else
        COMPREPLY=($(compgen -f -- "$cur"))
      fi
      ;;
    run|exec|shell|sh|status|stop|close|exit)
      COMPREPLY=($(compgen -W "$(_ssh_hold_names)" -- "$cur"))
      ;;
  esac
}

complete -F _ssh_hold ssh-hold
