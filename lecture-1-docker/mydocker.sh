#!/usr/bin/env bash
set -euo pipefail

BASE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
API="$BASE/api/api"
SECCOMP="$BASE/seccomp/seccomp_exec"
CGROUP="${CGROUP_PARENT:-/sys/fs/cgroup}/mydocker-$$"
LAUNCHER_PID=""
API_PID=""
CGROUP_CREATED=0

if [[ $EUID -eq 0 ]]; then
    echo "Run as a regular user, not with sudo" >&2
    exit 1
fi
for command in unshare nsenter setpriv hostname ip curl; do
    command -v "$command" >/dev/null || { echo "Missing command: $command" >&2; exit 1; }
done
for binary in "$API" "$SECCOMP"; do
    if [[ ! -x "$binary" ]]; then
        echo "Build the binary first (see README): $binary" >&2
        exit 1
    fi
done

# A delegated parent can be used without sudo; otherwise only cgroup setup needs root.
ADMIN=()
if [[ ! -w "$(dirname -- "$CGROUP")" ]]; then
    sudo -v
    ADMIN=(sudo)
fi
cleanup() {
    trap - EXIT INT TERM
    if [[ -n "$LAUNCHER_PID" ]]; then
        kill -KILL "$LAUNCHER_PID" 2>/dev/null || true
        wait "$LAUNCHER_PID" 2>/dev/null || true
    fi
    if [[ $CGROUP_CREATED -eq 1 && -d "$CGROUP" ]]; then
        echo '[mydocker] Final memory.events:'
        cat "$CGROUP/memory.events" 2>/dev/null || true
        # The group belongs only to this invocation, including any test children.
        echo 1 | "${ADMIN[@]}" tee "$CGROUP/cgroup.kill" >/dev/null || true
        for ((attempt=0; attempt<50; attempt++)); do
            if "${ADMIN[@]}" rmdir "$CGROUP" 2>/dev/null; then break; fi
            sleep 0.1
        done
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

"${ADMIN[@]}" mkdir "$CGROUP"
CGROUP_CREATED=1
for controller in memory cpu pids; do
    if [[ ! -e "$CGROUP/$controller.max" ]]; then
        echo "Enable $controller in the parent's cgroup.subtree_control first" >&2
        exit 1
    fi
done
echo 67108864 | "${ADMIN[@]}" tee "$CGROUP/memory.max" >/dev/null
echo 0 | "${ADMIN[@]}" tee "$CGROUP/memory.swap.max" >/dev/null
echo '50000 100000' | "${ADMIN[@]}" tee "$CGROUP/cpu.max" >/dev/null
echo 32 | "${ADMIN[@]}" tee "$CGROUP/pids.max" >/dev/null

echo "[mydocker] Cgroup: $CGROUP"
# BASHPID is the child shell, unlike $$ (the parent in a Bash subshell).
# Joining before unshare/exec charges startup allocations and all descendants here.
(
    CHILD_PID=$BASHPID
    echo "$CHILD_PID" | "${ADMIN[@]}" tee "$CGROUP/cgroup.procs" >/dev/null
    exec unshare --user --map-root-user --pid --fork --kill-child=SIGKILL \
        --mount --mount-proc --net --uts --ipc sh -ec '
            hostname mycontainer
            ip link set lo up
            exec setpriv --bounding-set=-all --no-new-privs "$2" "$1"
        ' sh "$API" "$SECCOMP"
) &
LAUNCHER_PID=$!

# unshare --fork has one child: the process that execs the API as namespace PID 1.
for ((attempt=0; attempt<100; attempt++)); do
    if ! kill -0 "$LAUNCHER_PID" 2>/dev/null; then
        echo '[mydocker] Isolated process exited during startup' >&2
        exit 1
    fi
    if [[ -r "/proc/$LAUNCHER_PID/task/$LAUNCHER_PID/children" ]]; then
        read -r API_PID _ < "/proc/$LAUNCHER_PID/task/$LAUNCHER_PID/children" || true
    fi
    if [[ -n "$API_PID" ]] && \
        [[ $(nsenter -t "$API_PID" --user --preserve-credentials --net curl -fsS --max-time 1 \
            http://127.0.0.1:8080/health 2>/dev/null || true) == ok ]]; then
        echo "[mydocker] Host PID: $API_PID"
        echo '[mydocker] Health: ok'
        echo '[mydocker] Running. Press Ctrl+C to stop.'
        wait "$LAUNCHER_PID"
        exit $?
    fi
    sleep 0.1
done
echo '[mydocker] API did not become ready' >&2
exit 1
