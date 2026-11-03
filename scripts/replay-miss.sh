#!/usr/bin/env bash
# Prove the replay miss message: append one sentence to the agent's system prompt, run the
# INC-1042 replay tests in strict mode in both languages and require each run to fail with the
# miss that names the changed component and the re-record command. The prompt is restored on
# every exit, including SIGINT and SIGTERM: this shell is the parent of the stack, so the stack's
# own shutdown cannot kill it before the trap runs. Run through `make replay-miss`.
set -euo pipefail

prompt=agent-spec/system-prompt.txt
backup="$(mktemp)"
output="$(mktemp)"
cp -p "$prompt" "$backup"
trap 'cp -p "$backup" "$prompt"; rm -f "$backup" "$output"' EXIT
trap 'exit 130' INT TERM

printf '\nAlways thank the customer by name.\n' >> "$prompt"
git diff --stat -- "$prompt"

prefix='replay miss: system prompt changed (hash '
command='re-record with `attest capture --refresh inc-1042`'
status=0
for lang in py ts; do
  echo
  echo "== $lang: strict replay with the changed system prompt =="
  if uv run --no-project --python 3.12 python scripts/stack.py -- make --no-print-directory "replay-run-$lang" CHANNEL="$CHANNEL" > "$output" 2>&1; then
    cat "$output"
    echo "FAIL: $lang replay passed although the system prompt changed" >&2
    status=1
    continue
  fi
  grep -F -- "$prefix" "$output" | head -n 1 || { cat "$output"; echo "FAIL: $lang output has no '$prefix'" >&2; status=1; }
  grep -qF -- "$command" "$output" || { cat "$output"; echo "FAIL: $lang output has no '$command'" >&2; status=1; }
done
exit "$status"
