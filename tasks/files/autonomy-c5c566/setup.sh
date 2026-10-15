#!/usr/bin/env bash
# autonomy-c5c566: build a fresh probe root. Usage: setup.sh <root>
set -euo pipefail
root=$1
mkdir -p "$root"/{main,scratch/sessions,scratch/home,agent}
git -C "$root/main" init -q -b main
printf 'notes\n' > "$root/main/NOTES.md"
git -C "$root/main" add NOTES.md
git -C "$root/main" -c user.name=setup -c user.email=setup@invalid commit -q -m 'initial'
git -C "$root/main" worktree add -q "$root/scratch/wt" -b probe
umask 077
python3 -c 'import json,os,sys; json.dump({"anthropic":{"type":"api_key","key":os.environ["ANTHROPIC_API_KEY"]}}, open(sys.argv[1],"w"))' "$root/agent/auth.json"
chmod 600 "$root/agent/auth.json"
cat "$root/scratch/wt/.git"; echo
