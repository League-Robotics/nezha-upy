"""Deploy user programs to a robot's filesystem.

The firmware tier (core/, hardware/, devices/, boot) is frozen into ROM
and needs ./build.sh + a flash. THIS tool handles the other tier: the
user programs and the robot config, which land on the ~20 KB device
filesystem and deploy in seconds.

Before this existed the procedure was hand-typed `mpremote fs cp`
against hand-generated stripped files, and the robot.json strip
transform lived only as prose in a bench log. Three failure modes came
with that, all fixed here:

  * the filesystem budget was discovered at the bench as
    "No space left on device" -- checked up front now;
  * the target was picked by port or drive letter -- resolved by UID
    and confirmed against the device's own identity now;
  * nothing verified what actually landed -- sizes are read back now.

Usage:
  python3 tools/deploy.py tovez [--port /dev/cu.usbmodemXXX] [--dry-run]
"""
import argparse
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The micro:bit flat filesystem is a 24576 B region, but microbitfs.c
# reserves a page and carves the rest into 160 chunks of 126 usable
# bytes. 20160 is the real payload ceiling; using 24576 would let a
# deploy pass here and then fail on the device.
FS_PAYLOAD_BUDGET = 160 * 126

MPY_CROSS = os.path.join(
    REPO, "micropython-microbit-v2", "lib", "micropython",
    "mpy-cross", "mpy-cross")

# Deployed as compiled bytecode: no on-device compilation, so no parse
# heap spike. Order is cosmetic (report only).
USER_PROGRAMS = ("main.py", "demo_square.py", "demo_util.py")


def strip_config(doc):
    """Drop `_`-prefixed keys recursively.

    The repo's data/<robot>.json is the documented source of truth and
    carries extensive `_`-prefixed annotation -- tovez's is 61 KB, which
    does not remotely fit. This is the device-flash-time transform
    described in data/README.md, encoded here so it stops being prose.
    """
    if isinstance(doc, dict):
        return {k: strip_config(v) for k, v in doc.items()
                if not k.startswith("_")}
    if isinstance(doc, list):
        return [strip_config(v) for v in doc]
    return doc


def build_artifacts(robot, outdir):
    """Produce the exact bytes that will land on the device."""
    artifacts = []

    src_json = os.path.join(REPO, "data", "%s.json" % robot)
    if not os.path.exists(src_json):
        sys.exit("no config for %r at %s" % (robot, src_json))
    with open(src_json) as f:
        doc = json.load(f)
    compact = json.dumps(strip_config(doc), separators=(",", ":"))
    dst = os.path.join(outdir, "robot.json")
    with open(dst, "w") as f:
        f.write(compact)
    artifacts.append(("robot.json", src_json, dst,
                      os.path.getsize(src_json), len(compact.encode())))

    if not os.path.exists(MPY_CROSS):
        sys.exit("mpy-cross not built at %s -- run ./build.sh first" % MPY_CROSS)
    for name in USER_PROGRAMS:
        src = os.path.join(REPO, "src", name)
        if not os.path.exists(src):
            continue
        out = os.path.join(outdir, name.replace(".py", ".mpy"))
        r = subprocess.run([MPY_CROSS, "-O3", "-o", out, src],
                           capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit("mpy-cross failed on %s:\n%s" % (name, r.stderr))
        artifacts.append((os.path.basename(out), src, out,
                          os.path.getsize(src), os.path.getsize(out)))
    return artifacts


def resolve_port(robot, explicit):
    """Find the robot by UID, never by port order or drive letter."""
    if explicit:
        return explicit
    with open(os.path.join(REPO, "config", "devices.json")) as f:
        devices = json.load(f)
    want = None
    for uid, entry in devices.items():
        if entry.get("board_name") == robot:
            want = uid
            break
    if want is None:
        sys.exit("robot %r not in config/devices.json" % robot)
    out = subprocess.run(["mpremote", "devs"], capture_output=True, text=True)
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) > 1 and parts[1] == want:
            return parts[0]
    sys.exit("robot %r (uid %s...) is not on the USB bus" % (robot, want[:20]))


def _mpremote(port, *args, retries=4):
    """mpremote, retried: a running main.py holds the REPL, and the
    known TLM-flood defect can block the raw-REPL handshake outright."""
    last = None
    for _ in range(retries):
        r = subprocess.run(["mpremote", "connect", port] + list(args),
                           capture_output=True, text=True, timeout=90)
        if r.returncode == 0:
            return r
        last = r
    return last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("robot")
    ap.add_argument("--port", default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    outdir = os.path.join(REPO, ".tmp", "deploy")
    os.makedirs(outdir, exist_ok=True)
    artifacts = build_artifacts(a.robot, outdir)

    print("  %-16s %10s %10s" % ("file", "source", "deployed"))
    total = 0
    for name, src, _dst, src_size, out_size in artifacts:
        print("  %-16s %9dB %9dB" % (name, src_size, out_size))
        total += out_size
    print("  %-16s %10s %9dB  of %dB budget" % ("TOTAL", "", total,
                                                FS_PAYLOAD_BUDGET))
    if total > FS_PAYLOAD_BUDGET:
        sys.exit("\nWOULD NOT FIT: %d B over budget. Nothing was written."
                 % (total - FS_PAYLOAD_BUDGET))
    if a.dry_run:
        print("\ndry run -- nothing written")
        return

    port = resolve_port(a.robot, a.port)
    print("\n  target %s on %s" % (a.robot, port))

    # Confirm the device agrees about who it is before writing to it.
    r = _mpremote(port, "exec",
                  "import json\n"
                  "try:\n"
                  "    f=open('robot.json'); d=json.load(f); f.close()\n"
                  "    print('IDENT', d['identity']['robot_name'])\n"
                  "except Exception:\n"
                  "    print('IDENT <none>')\n")
    ident = ""
    if r and r.returncode == 0:
        for line in r.stdout.splitlines():
            if line.startswith("IDENT"):
                ident = line.split(None, 1)[1].strip()
    if ident and ident != "<none>" and ident != a.robot:
        sys.exit("device identifies as %r, not %r -- refusing to deploy.\n"
                 "Pass --port explicitly if this is deliberate." % (ident, a.robot))
    print("  device identity: %s" % (ident or "<unreadable>"))

    for name, _src, dst, _ss, out_size in artifacts:
        r = _mpremote(port, "fs", "cp", dst, ":" + name)
        ok = r is not None and r.returncode == 0
        print("  %-16s %s" % (name, "copied" if ok else "FAILED"))
        if not ok:
            sys.exit("deploy failed on %s:\n%s" % (name, r.stderr if r else ""))

    r = _mpremote(port, "exec",
                  "import os\n"
                  "print('ONDEVICE', [(n, os.stat(n)[6]) for n in os.listdir()])\n")
    if r and r.returncode == 0:
        for line in r.stdout.splitlines():
            if line.startswith("ONDEVICE"):
                print("\n  verified: %s" % line[9:].strip())
    print("\n  reset the board for the new programs to run")


if __name__ == "__main__":
    main()
