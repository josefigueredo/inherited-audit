#!/usr/bin/env bash
# Install the inherited-audit and inherited-fix skills for Claude Code and Cursor, or for Cursor only.
#   ./install.sh            link skill/ into ~/.claude/skills/inherited-audit and fix-skill/ into
#                           ~/.claude/skills/inherited-fix (Claude Code and Cursor read them)
#   ./install.sh --cursor   link both into ~/.cursor/skills/ instead (Cursor only)
#   ./install.sh --agents   also link the optional subagent definitions:
#                           agents/claude/ia-auditor.md -> ~/.claude/agents/ia-auditor.md (not with --cursor)
#                           agents/cursor/ia-auditor.md -> ~/.cursor/agents/ia-auditor.md
# Only skill/ and fix-skill/ are linked, so docs/ and tests/ are never installed. Cursor reads ~/.claude/skills and
# ~/.cursor/skills, so each skill goes into one of them, never both, and never into ~/.agents/skills (Cursor would
# load it twice).
# inherited-fix calls the inherited-audit CLI as its sibling folder, so both go into the same skills folder.
# Re-running is safe. A real file or directory at a link path is never replaced: the script stops with exit 1.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME="inherited-audit"
FIX_NAME="inherited-fix"
AGENTS=0
CURSOR=0
for arg in "$@"; do
  case "$arg" in
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    --agents) AGENTS=1 ;;
    --cursor) CURSOR=1 ;;
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

if [ "$CURSOR" = 1 ]; then
  DIR="$HOME/.cursor/skills" OTHER_DIR="$HOME/.claude/skills"
else
  DIR="$HOME/.claude/skills" OTHER_DIR="$HOME/.cursor/skills"
fi
for name in "$NAME" "$FIX_NAME"; do
  if [ -e "$OTHER_DIR/$name" ] || [ -L "$OTHER_DIR/$name" ]; then
    echo "refusing to link $DIR/$name: $OTHER_DIR/$name is there, and Cursor would load the skill twice;" \
      "remove it and re-run" >&2
    exit 1
  fi
done
status=0
link "$REPO/skill" "$DIR/$NAME" || exit 1
echo "skill: $DIR/$NAME -> $REPO/skill"
link "$REPO/fix-skill" "$DIR/$FIX_NAME" || exit 1
echo "skill: $DIR/$FIX_NAME -> $REPO/fix-skill"
if [ "$AGENTS" = 1 ]; then
  if [ "$CURSOR" = 1 ]; then
    link "$REPO/agents/cursor/ia-auditor.md" "$HOME/.cursor/agents/ia-auditor.md" || status=1
    [ "$status" = 0 ] && echo "agents: ia-auditor linked for Cursor"
  else
    link "$REPO/agents/claude/ia-auditor.md" "$HOME/.claude/agents/ia-auditor.md" || status=1
    link "$REPO/agents/cursor/ia-auditor.md" "$HOME/.cursor/agents/ia-auditor.md" || status=1
    [ "$status" = 0 ] && echo "agents: ia-auditor linked for Claude Code and Cursor"
  fi
fi
command -v python3 >/dev/null || { echo "note: python3 is not on PATH; ia.py needs it" >&2; status=1; }
command -v git >/dev/null || { echo "note: git is not on PATH; ia.py needs git 2.38+" >&2; status=1; }
exit "$status"
