#!/bin/zsh

# Shared lock helpers for the manual sync and requested-sync watcher.

acquire_sync_lock() {
  local lock_dir="$1"
  local owner_pid lock_mtime now lock_age stale_dir

  mkdir -p "$(dirname "$lock_dir")"

  while ! mkdir "$lock_dir" 2>/dev/null; do
    owner_pid=""
    if [[ -r "$lock_dir/pid" ]]; then
      IFS= read -r owner_pid < "$lock_dir/pid" || true
    fi

    if [[ "$owner_pid" == <-> ]] && kill -0 "$owner_pid" 2>/dev/null; then
      return 1
    fi

    # Old versions created an empty lock directory. Give a new process time
    # to write its PID, and keep legacy locks while either sync script exists.
    if [[ ! -r "$lock_dir/pid" || "$owner_pid" != <-> ]]; then
      if pgrep -f '/scripts/[r]un_sync\.sh|/scripts/[r]un_requested_sync\.sh' \
        | awk -v current_pid="$$" '$1 != current_pid { found=1 } END { exit !found }'; then
        return 1
      fi

      lock_mtime="$(stat -f %m "$lock_dir" 2>/dev/null || print 0)"
      now="$(date +%s)"
      lock_age=$((now - lock_mtime))
      if (( lock_age < 60 )); then
        return 1
      fi
    fi

    # Move a dead lock aside atomically so the next mkdir can claim the path.
    # A unique destination prevents collisions between simultaneous recoveries.
    stale_dir="${lock_dir}.stale.$$.$RANDOM"
    if mv "$lock_dir" "$stale_dir" 2>/dev/null; then
      rm -f "$stale_dir/pid"
      rmdir "$stale_dir" 2>/dev/null || true
    else
      return 1
    fi
  done

  if ! printf '%s\n' "$$" > "$lock_dir/pid"; then
    rmdir "$lock_dir" 2>/dev/null || true
    return 2
  fi
  return 0
}

release_sync_lock() {
  local lock_dir="$1"
  local owner_pid=""

  if [[ -r "$lock_dir/pid" ]]; then
    IFS= read -r owner_pid < "$lock_dir/pid" || true
  fi
  if [[ "$owner_pid" == "$$" ]]; then
    rm -f "$lock_dir/pid"
    rmdir "$lock_dir" 2>/dev/null || true
  fi
}
