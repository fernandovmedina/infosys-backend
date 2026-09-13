#!/usr/bin/env bash
# detect.sh — let Claude detect tmux/cmux sessions and drive other panes
# (e.g. Codex or another Claude worker) by sending input and reading output.
#
# Usage:
#   scripts/detect.sh [status]                 Detect multiplexer, caller pane, and all panes (+ agent running in each)
#   scripts/detect.sh workers                  List only panes running codex/claude (excluding the caller)
#   scripts/detect.sh read  <target> [lines]   Print the last N lines of a pane (default 60)
#   scripts/detect.sh send  <target> <text>    Type text into a pane and press Enter
#   scripts/detect.sh type  <target> <text>    Type text into a pane WITHOUT pressing Enter
#   scripts/detect.sh key   <target> <key>     Send a key (enter, escape, ctrl+c, tab, ...)
#   scripts/detect.sh wait  <target> [timeout] [idle]  Block until pane output is stable for <idle>s (default 300s / 8s)
#   scripts/detect.sh ask   <target> <text> [timeout]  send + wait + read (one-shot delegation)
#
# Targets:
#   cmux  -> surface ref / index / UUID, e.g. surface:9
#   tmux  -> any tmux target, e.g. work:1.0 or %3
#
# Backend is chosen automatically: cmux if its socket responds, otherwise tmux.
# Force one with MUX=cmux or MUX=tmux.

set -uo pipefail

err() { printf 'detect.sh: %s\n' "$*" >&2; }
die() { err "$*"; exit 1; }

have() { command -v "$1" >/dev/null 2>&1; }

cmux_up() { have cmux && cmux ping >/dev/null 2>&1; }
tmux_up() { have tmux && tmux list-sessions >/dev/null 2>&1; }

backend() {
  if [ -n "${MUX:-}" ]; then echo "$MUX"; return; fi
  if cmux_up; then echo cmux
  elif tmux_up; then echo tmux
  else echo none
  fi
}

# Classify a process command line as codex / claude / "".
# Reads "pid<TAB>args" lines on stdin, prints "pid<TAB>agent" for matches.
classify_procs() {
  awk -F'\t' '{
    a = $2
    if (a ~ /(^|[\/ ])codex( |$)/ && a !~ /cmux-cli-shims/) print $1 "\tcodex"
    else if (a ~ /(^|[\/ ])claude( |$)/ && a !~ /cmux-cli-shims/) print $1 "\tclaude"
  }'
}

all_procs() { ps -ax -o pid=,args= | sed -E 's/^ *([0-9]+) +/\1\t/'; }

# ---------------------------------------------------------------- cmux ----

cmux_caller() {
  cmux identify 2>/dev/null | awk -F'"' '/"caller"/{c=1} c && /surface_ref/{print $4; exit}'
}

# Prints: surface<TAB>workspace-name<TAB>title
cmux_surfaces() {
  cmux tree --all 2>/dev/null | awk '
    /workspace workspace:/ { match($0, /"[^"]*"/); ws = substr($0, RSTART+1, RLENGTH-2) }
    /surface surface:/ {
      match($0, /surface:[0-9]+/); ref = substr($0, RSTART, RLENGTH)
      t = ""; if (match($0, /\] "[^"]*"/)) t = substr($0, RSTART+3, RLENGTH-4)
      printf "%s\t%s\t%s\n", ref, ws, t
    }'
}

# Prints: surface<TAB>agent   (codex/claude running somewhere under that surface)
cmux_agents() {
  awk -F'\t' '
    NR == FNR {
      if ($4 == "process") {
        pid = $5; parent = $6
        if (parent ~ /^surface:/) own[pid] = parent
        else if (parent ~ /^[0-9]+$/ && (parent in own)) own[pid] = own[parent]
      }
      next
    }
    ($1 in own) { print own[$1] "\t" $2 }
  ' <(cmux top --all --processes --format tsv 2>/dev/null) <(all_procs | classify_procs) | sort -u
}

cmux_status() {
  local caller agents
  caller=$(cmux_caller)
  agents=$(cmux_agents)
  echo "caller: ${caller:-unknown}"
  echo "panes:"
  cmux_surfaces | while IFS=$'\t' read -r ref ws title; do
    agent=$(printf '%s\n' "$agents" | awk -F'\t' -v r="$ref" '$1 == r { printf "%s%s", sep, $2; sep = "," }')
    mark=""; [ "$ref" = "$caller" ] && mark=" (me)"
    printf '  %-12s agent=%-7s workspace=%-12s title=%s%s\n' "$ref" "${agent:-shell}" "$ws" "$title" "$mark"
  done
}

cmux_workers() {
  local caller; caller=$(cmux_caller)
  cmux_agents | awk -F'\t' -v me="$caller" '$1 != me'
}

cmux_read() { cmux read-screen --surface "$1" --scrollback --lines "${2:-60}"; }
cmux_type() { cmux send --surface "$1" -- "$2"; }
cmux_key()  { cmux send-key --surface "$1" -- "$2"; }

# ---------------------------------------------------------------- tmux ----

tmux_caller() { [ -n "${TMUX_PANE:-}" ] && tmux display-message -p -t "$TMUX_PANE" '#{session_name}:#{window_index}.#{pane_index}'; }

# Prints: target<TAB>pane_pid<TAB>current_command<TAB>title
tmux_panes() {
  tmux list-panes -a -F '#{session_name}:#{window_index}.#{pane_index}	#{pane_pid}	#{pane_current_command}	#{pane_title}' 2>/dev/null
}

# Prints: target<TAB>agent   (codex/claude descending from that pane's shell)
tmux_agents() {
  awk -F'\t' '
    FILENAME == ARGV[1] { par[$1] = $2; next }
    FILENAME == ARGV[2] { root[$2] = $1; next }
    { p = $1; while (p != "" && p != "0" && p != "1") { if (p in root) { print root[p] "\t" $2; break } p = par[p] } }
  ' <(ps -ax -o pid=,ppid= | awk '{print $1 "\t" $2}') <(tmux_panes) <(all_procs | classify_procs) | sort -u
}

tmux_status() {
  local caller agents
  caller=$(tmux_caller)
  agents=$(tmux_agents)
  echo "caller: ${caller:-not inside tmux}"
  echo "panes:"
  tmux_panes | while IFS=$'\t' read -r target _ cmd title; do
    agent=$(printf '%s\n' "$agents" | awk -F'\t' -v r="$target" '$1 == r { printf "%s%s", sep, $2; sep = "," }')
    mark=""; [ "$target" = "$caller" ] && mark=" (me)"
    printf '  %-14s agent=%-7s cmd=%-10s title=%s%s\n' "$target" "${agent:-shell}" "$cmd" "$title" "$mark"
  done
}

tmux_workers() {
  local caller; caller=$(tmux_caller)
  tmux_agents | awk -F'\t' -v me="$caller" '$1 != me'
}

tmux_read() { tmux capture-pane -p -J -t "$1" -S "-${2:-60}"; }
tmux_type() { tmux send-keys -t "$1" -l -- "$2"; }
tmux_key() {
  local k="$2"
  case "$k" in
    enter) k=Enter ;; escape|esc) k=Escape ;; tab) k=Tab ;; backspace) k=BSpace ;;
    ctrl+?) k="C-${k#ctrl+}" ;;
  esac
  tmux send-keys -t "$1" "$k"
}

# ------------------------------------------------------------- common ----

B=$(backend)

need_backend() { [ "$B" = none ] && die "no running cmux or tmux session detected"; }
call() { "${B}_$1" "${@:2}"; }

cmd_status() {
  echo "cmux: $(cmux_up && echo running || echo 'not running')${CMUX_SURFACE_ID:+ (inside cmux)}"
  echo "tmux: $(tmux_up && echo running || echo 'not running')${TMUX:+ (inside tmux)}"
  echo "backend: $B"
  [ "$B" = none ] && return 1
  call status
}

cmd_send() {
  call type "$1" "$2" || return 1
  sleep 0.3                     # let TUIs (codex/claude) ingest the paste before Enter
  call key "$1" enter
}

# Wait until the pane content stops changing for <idle> seconds.
cmd_wait() {
  local target=$1 timeout=${2:-300} idle=${3:-8}
  local prev="" cur stable=0 elapsed=0
  while [ "$elapsed" -lt "$timeout" ]; do
    cur=$(call read "$target" 40 2>/dev/null | cksum)
    if [ "$cur" = "$prev" ]; then
      stable=$((stable + 2))
      [ "$stable" -ge "$idle" ] && return 0
    else
      stable=0; prev=$cur
    fi
    sleep 2; elapsed=$((elapsed + 2))
  done
  err "timeout after ${timeout}s waiting for $target to go idle"
  return 124
}

usage() { sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'; }

sub=${1:-status}; shift 2>/dev/null || true
case "$sub" in
  status)   cmd_status ;;
  workers)  need_backend; call workers ;;
  read)     need_backend; [ $# -ge 1 ] || die "usage: read <target> [lines]"; call read "$1" "${2:-60}" ;;
  send)     need_backend; [ $# -ge 2 ] || die "usage: send <target> <text>"; cmd_send "$1" "$2" ;;
  type)     need_backend; [ $# -ge 2 ] || die "usage: type <target> <text>"; call type "$1" "$2" ;;
  key)      need_backend; [ $# -ge 2 ] || die "usage: key <target> <key>"; call key "$1" "$2" ;;
  wait)     need_backend; [ $# -ge 1 ] || die "usage: wait <target> [timeout] [idle]"; cmd_wait "$@" ;;
  ask)      need_backend; [ $# -ge 2 ] || die "usage: ask <target> <text> [timeout]"
            cmd_send "$1" "$2" && sleep 3 && cmd_wait "$1" "${3:-300}"; call read "$1" 80 ;;
  -h|--help|help) usage ;;
  *)        usage; exit 2 ;;
esac
