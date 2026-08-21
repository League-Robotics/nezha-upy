"""Square-tour bench runner for nezha-upy: drives the tour on the robot
over USB serial (mpremote exec), captures per-cycle telemetry, integrates
odometry host-side, and renders the standard two-pane chart.

The on-device move engine is a Python port of pxt-nezha-diffdrive's
serviceMove(): acceleration ramp from a floor scale over ~400 ms,
end-of-move taper over ~32 mm / ~15 deg windows, tighter margin and
slower final crawl for pure turns, and a drive() reissue every poll
with a rolling 500 ms lease. Same kernel API, no vendor changes.

Usage:
  python3 tools/tour_run.py PORT --robot tovez [--side-mm 500]
      [--speed 150] [--out PNG]
"""
import argparse
import math
import subprocess
import sys
import time

# Design values in mm/s -- multiplied by the robot's REAL ticks/mm at
# build time. The old table hardcoded counts computed from 3.8424
# ticks/mm (the disproven calibration), leaving every limit 3.3x too
# small on a robot that actually reads 12.76.
G = dict(
    max_duty=100.0, full_duty_velocity=10715.0,   # MEASURED (tools/plant_id.py)
    kp=0.0, ki=6.0,
    i_max_mm=60.0, pid_max_mm=100.0, pos_err_mm=10.0,
    v_min_mm=20.0, bias_max_mm=23.8, a_steady_mm=30.0,
    stall_speed_mm=15.0, twist_hold=2.0,
    wheel_gain_left=0.892, wheel_gain_right=1.108,  # MEASURED
)

DEVICE_SCRIPT = r"""
import gc, time, diffdrive
gc.collect()
diffdrive.configure(left_port=2, right_port=1, fwd_sign_left=-1,
    fwd_sign_right=1, max_duty=%(maxduty)f, cycle_period_ms=32,
    full_duty_velocity=%(fdv)f, pid_kp=%(kp)f, pid_ki=%(ki)f,
    pid_i_max=%(imax)f, pid_kaff=0.0, pid_max=%(pidmax)f,
    pos_err_max=%(poserr)f, v_min=%(vmin)f, bias_max=%(biasmax)f,
    tau_adapt=30.0, a_steady=%(asteady)f, twist_hold_gain=%(twist)f,
    stall_speed=%(stallspd)f, stall_demand=0.0, stall_window=500.0,
    wheel_gain_left=%(wgl)f, wheel_gain_right=%(wgr)f,
    wheel_intercept_left=0.0, wheel_intercept_right=0.0)
diffdrive.begin()
# NO start(): step-driven mode. Python owns the cadence, so there is
# no kernel fiber to starve and the period is what we asked for.
# Warm-up matters here: output()['ready'] (and drive()'s commandable
# check) only becomes true once a cycle has actually run, and in step
# mode nothing runs until we call step() ourselves.
for _ in range(6):
    diffdrive.step()
    time.sleep_ms(32)
o = diffdrive.output()
print('READY', o['ready'])
CPM = %(cpm)f
TRACK = %(track)f
def tlm():
    o = diffdrive.output()
    print('T,%%d,%%.1f,%%.1f,%%.1f,%%.1f' %% (time.ticks_ms(),
        o['positionLeft'], o['positionRight'],
        o['velocityLeft'], o['velocityRight']))
    return o
def move(dmm, ydeg, spd, yr):
    o = diffdrive.output()
    p0l = o['positionLeft']; p0r = o['positionRight']
    dt = dmm * CPM
    yt = ydeg * 0.0174533 * 0.5 * TRACK * CPM
    dur = 0.0
    if dt: dur = abs(dt) / (spd * CPM)
    if yt:
        yd = abs(yt) / (yr * 0.0174533 * 0.5 * TRACK * CPM)
        if yd > dur: dur = yd
    if dur <= 0: return
    vel = dt / dur; tw = yt / dur
    pure = (yt != 0 and dt == 0)
    floor = 0.36 if pure else 0.18
    dmargin = 30.0; ymargin = 14.0 if pure else 30.0
    start = time.ticks_ms()
    deadline = int(dur * 1800) + 4000
    print('PH,loop,%%d' %% time.ticks_ms())
    P = diffdrive.cyclePeriod()
    cycle = time.ticks_ms()
    diffdrive.drive(vel * floor, tw * floor, 500)
    while True:
        o = tlm()
        dl = o['positionLeft'] - p0l; dr = o['positionRight'] - p0r
        mp = (dl + dr) * 0.5; dp = (dr - dl) * 0.5
        scale = 1.0; dd = True; yd_ = True
        if dt:
            rem = abs(dt) - abs(mp); dd = rem <= dmargin
            s = rem / 600.0
            if s < scale: scale = s
        if yt:
            rem = abs(yt) - abs(dp); yd_ = rem <= ymargin
            s = rem / 360.0
            if s < scale: scale = s
        if scale < floor: scale = floor
        ramp = time.ticks_diff(time.ticks_ms(), start) / 400.0
        if ramp < floor: ramp = floor
        if ramp < scale: scale = ramp
        if scale > 1.0: scale = 1.0
        if dd and yd_: break
        if o['stallHalted']:
            print('STALL'); break
        if time.ticks_diff(time.ticks_ms(), start) > deadline:
            print('TIMEOUT'); break
        diffdrive.drive(vel * scale, tw * scale, 500)
        w = time.ticks_diff(cycle, time.ticks_ms())
        if w > 0:
            time.sleep_ms(w)
        cycle = time.ticks_add(cycle, P)
        diffdrive.step()
    print('PH,brake,%%d' %% time.ticks_ms())
    # neutral(), NOT drive(0,0): with a 100%% rail and kp>0 a commanded
    # zero is an ACTIVE hold that reverses past the target -- measured a
    # consistent -4.2 deg pull-back on turns. neutral() stages a true stop.
    diffdrive.neutral()
    for _ in range(6):
        diffdrive.step(); tlm(); time.sleep_ms(25)
    print('PH,settle,%%d' %% time.ticks_ms())
    diffdrive.neutral()
    for _ in range(14):
        diffdrive.step(); tlm(); time.sleep_ms(25)
    o = diffdrive.output()
    dl = o['positionLeft'] - p0l; dr = o['positionRight'] - p0r
    print('MV,%%.1f,%%.1f,%%.1f,%%.1f' %% (dt, yt, (dl+dr)*0.5, (dr-dl)*0.5))
for _leg in range(4):
    move(%(side)f, 0.0, %(speed)f, 90.0)
    move(0.0, 90.0, %(speed)f, 60.0)
diffdrive.neutral()
print('DONE')
"""


def _interrupt(port):
    """Break into a running main.py so raw REPL entry succeeds."""
    try:
        import serial
        s = serial.Serial(port, 115200, timeout=0.3)
        for _ in range(3):
            s.write(b'\x03'); time.sleep(0.4)
        s.close()
        time.sleep(0.8)
    except Exception:
        pass


def capture(port, side_mm, speed, cpm, track):
    tpm = cpm
    script = DEVICE_SCRIPT % {
        'cpm': cpm, 'track': track, 'side': side_mm, 'speed': speed,
        'maxduty': G['max_duty'], 'fdv': G['full_duty_velocity'],
        'kp': G['kp'], 'ki': G['ki'], 'imax': G['i_max_mm'] * tpm,
        'pidmax': G['pid_max_mm'] * tpm, 'poserr': G['pos_err_mm'] * tpm,
        'vmin': G['v_min_mm'] * tpm, 'biasmax': G['bias_max_mm'] * tpm,
        'asteady': G['a_steady_mm'] * tpm, 'twist': G['twist_hold'],
        'stallspd': G['stall_speed_mm'] * tpm,
        'wgl': G['wheel_gain_left'], 'wgr': G['wheel_gain_right']}
    lines = []
    for attempt in range(4):
        _interrupt(port)
        r = subprocess.run(
            ['mpremote', 'connect', port, 'exec', script],
            capture_output=True, text=True, timeout=240)
        lines = (r.stdout + r.stderr).splitlines()
        if any(l.strip().startswith('T,') for l in lines):
            break
        time.sleep(2)
    rows = []
    status = {'ready': None, 'done': False, 'stall': 0, 'timeout': 0}
    for ln in lines:
        ln = ln.strip()
        if ln.startswith('T,'):
            p = ln.split(',')
            if len(p) == 6:
                try:
                    rows.append(tuple(float(v) for v in p[1:]))
                except ValueError:
                    pass  # corrupt sample; drop, never crash the run
        elif ln.startswith('MV,'):
            p2 = ln.split(',')
            rows.append(('MV',) + tuple(float(v) for v in p2[1:]))
        elif ln.startswith('PH,'):
            p2 = ln.split(',')
            rows.append(('PH', p2[1], float(p2[2])))
        elif ln.startswith('READY'):
            status['ready'] = ln
        elif ln == 'DONE':
            status['done'] = True
        elif ln == 'STALL':
            status['stall'] += 1
        elif ln == 'TIMEOUT':
            status['timeout'] += 1
    return rows, status


def clean(rows, cpm, max_step_mm=40.0):
    """Drop physically implausible samples (encoder glitches): any
    per-sample wheel delta beyond max_step_mm is a corrupt read, not
    motion -- same outlier hygiene as pxt tour_chart.py."""
    out = [rows[0]]
    dropped = 0
    for r in rows[1:]:
        dl = abs(r[1] - out[-1][1]) / cpm
        dr = abs(r[2] - out[-1][2]) / cpm
        if dl > max_step_mm or dr > max_step_mm:
            dropped += 1
            continue
        out.append(r)
    return out, dropped


def integrate(rows, cpm, track_mm):
    """Dead-reckon pose host-side from raw encoder counts."""
    xs, ys = [0.0], [0.0]
    h = 0.0
    for i in range(1, len(rows)):
        dl = (rows[i][1] - rows[i - 1][1]) / cpm   # [mm]
        dr = (rows[i][2] - rows[i - 1][2]) / cpm   # [mm]
        dc = (dl + dr) / 2.0
        dth = (dr - dl) / track_mm
        mid = h + dth / 2.0
        xs.append(xs[-1] + dc * math.cos(mid))
        ys.append(ys[-1] + dc * math.sin(mid))
        h += dth
    return xs, ys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('port')
    ap.add_argument('--robot', default='robot')
    ap.add_argument('--side-mm', type=float, default=500.0)
    ap.add_argument('--speed', type=float, default=100.0)  # [mm/s]
    ap.add_argument('--cpm', type=float, default=12.7602)  # [counts/mm]
    ap.add_argument('--track', type=float, default=115.0)  # [mm]
    ap.add_argument('--out', default='.tmp/tour.png')
    ap.add_argument('--no-open', action='store_true')
    ap.add_argument('--kp', type=float, default=None)
    ap.add_argument('--ki', type=float, default=None)
    a = ap.parse_args()

    if a.kp is not None:
        G['kp'] = a.kp
    if a.ki is not None:
        G['ki'] = a.ki
    rows, status = capture(a.port, a.side_mm, a.speed, a.cpm, a.track)
    print('samples:', len(rows), status)
    if len(rows) < 10:
        sys.exit('capture failed -- too few samples')
    markers = [(r[1], r[2]) for r in rows if r[0] == 'PH']
    moves = [r[1:] for r in rows if r[0] == 'MV']
    rows = [r for r in rows if r[0] not in ('PH', 'MV')]
    for dt_t, yt_t, mp, dp in moves:
        if dt_t:
            err = (abs(mp) - abs(dt_t)) / a.cpm
            print('MOVE leg   target %6.0fmm  overshoot %+6.1fmm' % (dt_t / a.cpm, err))
        else:
            err = (abs(dp) - abs(yt_t)) / a.cpm / a.track * 2 * 57.2958
            print('MOVE turn  target %6.0fdeg overshoot %+6.2fdeg' % (yt_t / a.cpm / a.track * 2 * 57.2958, err))
    rows, dropped = clean(rows, a.cpm)
    if dropped:
        print('glitch samples dropped:', dropped)
    # heading accrued between consecutive markers
    def heading_at(t_ms):
        h = 0.0
        for i in range(1, len(rows)):
            if rows[i][0] > t_ms: break
            h += ((rows[i][2] - rows[i-1][2]) - (rows[i][1] - rows[i-1][1])) \
                 / a.cpm / a.track
        return h
    prev = None
    for name, tm in markers:
        h = math.degrees(heading_at(tm))
        if prev is not None:
            print('PHASE %-8s heading %+7.1f deg  (delta %+6.1f)' % (prev[0], h, h - prev[1]))
        prev = (name, h)
    if prev:
        print('PHASE %-8s heading %+7.1f deg (final %+.1f)' % (prev[0], math.degrees(heading_at(1e12)), math.degrees(heading_at(1e12)) - prev[1]))

    xs, ys = integrate(rows, a.cpm, a.track)
    t0 = rows[0][0]
    ts = [(r[0] - t0) / 1000.0 for r in rows]
    vl = [r[3] / a.cpm / 10.0 for r in rows]   # [cm/s]
    vr = [r[4] / a.cpm / 10.0 for r in rows]

    closure = math.hypot(xs[-1] - xs[0], ys[-1] - ys[0])

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    S1, S2 = '#2a78d6', '#eb6834'
    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=(13, 6), gridspec_kw={'width_ratios': [1, 1.2]})
    side = a.side_mm
    sq_x = [0, side, side, 0, 0]
    sq_y = [0, 0, side, side, 0]
    ax1.plot(sq_x, sq_y, ':', color='#b9b7b0', lw=1.6,
             label='commanded square')
    ax1.plot(xs, ys, '-', color=S1, lw=1.8, label='odometry')
    ax1.plot(xs[0], ys[0], 'o', color='#2f9e44', ms=10, label='start')
    ax1.plot(xs[-1], ys[-1], 's', color='#e03131', ms=9, label='end')
    ax1.plot([xs[0], xs[-1]], [ys[0], ys[-1]], '--', color='#e03131',
             lw=1.0, alpha=0.7)
    ax1.annotate('closure %.0f mm' % closure,
                 xy=((xs[0] + xs[-1]) / 2, (ys[0] + ys[-1]) / 2),
                 fontsize=11, color='#e03131')
    ax1.set_xlabel('x [mm]'); ax1.set_ylabel('y [mm]')
    ax1.set_aspect('equal'); ax1.grid(alpha=0.25); ax1.legend(loc='best')
    ax1.set_title('trajectory (encoder odometry)')
    def smooth(v, n=7):
        out = []
        for i in range(len(v)):
            lo = max(0, i - n // 2); hi = min(len(v), i + n // 2 + 1)
            out.append(sum(v[lo:hi]) / (hi - lo))
        return out
    # raw stays visible -- smoothing the plot must not hide the data
    ax2.plot(ts, vl, color=S1, lw=0.6, alpha=0.25)
    ax2.plot(ts, vr, color=S2, lw=0.6, alpha=0.25)
    ax2.plot(ts, smooth(vl), color=S1, lw=1.6, label='left wheel')
    ax2.plot(ts, smooth(vr), color=S2, lw=1.6, label='right wheel')
    ax2.set_xlabel('time [s]'); ax2.set_ylabel('wheel speed [cm/s]')
    ax2.grid(alpha=0.25); ax2.legend(loc='best')
    ax2.set_title('wheel speeds (raw faint, 7-sample mean bold)')
    fig.suptitle('Square Tour — %s — %.0f cm sides — '
                 'closure %.0f mm' % (a.robot, a.side_mm / 10, closure),
                 fontsize=14)
    fig.tight_layout()
    import os
    os.makedirs(os.path.dirname(a.out) or '.', exist_ok=True)
    fig.savefig(a.out, dpi=130)
    print('closure_mm %.1f' % closure)
    print('png %s' % a.out)
    if not a.no_open:
        subprocess.run(['open', a.out])


if __name__ == '__main__':
    main()
