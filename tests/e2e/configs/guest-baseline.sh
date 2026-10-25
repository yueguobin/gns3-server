# Baseline configuration for a Linux guest on an e2e link — the reviewed
# artifact the scenarios stage (the qemu scenario pipes it through the
# console: harness.configure_linux). Idempotent by design: re-adding an
# address that is already configured fails softly ("File exists" is eaten),
# so re-running after a node restart — or twice on a warm guest — is
# harmless. `ip addr add` rather than `replace`: the appliance guest's
# busybox ip may not know the newer forms.
#
# usage: guest-baseline.sh <interface> [v4/prefixlen] [v6/prefixlen]
set -e
if=$1
if [ -n "$2" ]; then ip addr add "$2" dev "$if" 2>/dev/null || true; fi
if [ -n "$3" ]; then ip -6 addr add "$3" dev "$if" 2>/dev/null || true; fi
ip link set "$if" up
