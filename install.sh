#!/usr/bin/env bash
# Install the inherited-audit skill for Claude Code and Cursor.
#   ./install.sh            link skill/ into ~/.claude/skills/inherited-audit
#   ./install.sh --agents   also link the optional subagent definitions:
#                           agents/claude/ia-auditor.md -> ~/.claude/agents/ia-auditor.md
#                           agents/cursor/ia-auditor.md -> ~/.cursor/agents/ia-auditor.md
# Only skill/ is linked, so docs/ and tests/ are never installed. Cursor reads ~/.claude/skills
# too, so nothing goes into ~/.agents/skills (Cursor would load the skill twice).
# Re-running is safe. A real file or directory at a link path is never replaced: the script stops with exit 1.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME="inherited-audit"
AGENTS=0
for arg in "$@"; do
  case "$arg" in
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    --agents) AGENTS=1 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

link() {  # link <target> <path>: create or refresh a symlink, never replace a real file or directory
  if [ -e "$2" ] && [ ! -L "$2" ]; then
    echo "refusing to replace $2: it is not a symlink; move it away and re-run" >&2
    return 1
  fi
  mkdir -p "$(dirname "$2")"
  ln -sfn "$1" "$2"
}

status=0
link "$REPO/skill" "$HOME/.claude/skills/$NAME" || exit 1
echo "skill: $HOME/.claude/skills/$NAME -> $REPO/skill"
if [ "$AGENTS" = 1 ]; then
  link "$REPO/agents/claude/ia-auditor.md" "$HOME/.claude/agents/ia-auditor.md" || status=1
  link "$REPO/agents/cursor/ia-auditor.md" "$HOME/.cursor/agents/ia-auditor.md" || status=1
  [ "$status" = 0 ] && echo "agents: ia-auditor linked for Claude Code and Cursor"
fi
command -v python3 >/dev/null || { echo "note: python3 is not on PATH; ia.py needs it" >&2; status=1; }
command -v git >/dev/null || { echo "note: git is not on PATH; ia.py needs git 2.38+" >&2; status=1; }
exit "$status"
