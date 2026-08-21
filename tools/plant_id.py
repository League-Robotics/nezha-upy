"""Plant identification: measure each wheel's duty -> steady velocity.

Feedforward (full_duty_velocity) and the per-wheel gains are the
kernel's open-loop model. If they are wrong the integrator spends its
authority fighting the model instead of the disturbance, which reads as
wobble. Measure instead of inheriting.

Alternates direction each step so the robot stays roughly in place.
"""
import subprocess
import sys
import time

SCRIPT = r"""
import time, diffdrive
diffdrive.configure(left_port=2, right_port=1, fwd_sign_left=-1,
    fwd_sign_right=1, max_duty=100.0, cycle_period_ms=24,
    full_duty_velocity=0.0)     # 0 = raw duty mode, no feedforward
diffdrive.begin()
for duty in (15.0, 25.0, 35.0, 45.0, 60.0):
    for sign in (1.0, -1.0):
        diffdrive.driveDuty(duty * sign, duty * sign, 1500)
        for _ in range(10):
            diffdrive.step()          # spin-up
        acc_l = 0.0; acc_r = 0.0; n = 0
        for _ in range(18):           # steady-state window
            diffdrive.step()
            o = diffdrive.output()
            acc_l += o['velocityLeft']; acc_r += o['velocityRight']; n += 1
        print('P,%.1f,%.1f,%.1f,%.1f' % (duty, sign, acc_l / n, acc_r / n))
        diffdrive.neutral()
        for _ in range(8):
            diffdrive.step()
print('PDONE')
"""


def main():
    port = sys.argv[1]
    try:
        import serial
        s = serial.Serial(port, 115200, timeout=0.3)
        for _ in range(3):
            s.write(b'\x03'); time.sleep(0.4)
        s.close(); time.sleep(0.8)
    except Exception:
        pass
    r = subprocess.run(['mpremote', 'connect', port, 'exec', SCRIPT],
                       capture_output=True, text=True, timeout=240)
    rows = []
    for ln in (r.stdout + r.stderr).splitlines():
        if ln.startswith('P,'):
            d, sg, vl, vr = (float(v) for v in ln[2:].split(','))
            rows.append((d, sg, vl, vr))
    if not rows:
        print((r.stdout + r.stderr)[:400]); sys.exit('no samples')

    print('  duty   dir      velL      velR    |L|/duty  |R|/duty')
    sl = sr = 0.0
    n = 0
    for d, sg, vl, vr in rows:
        print('  %4.0f%%  %+.0f  %8.1f  %8.1f   %7.1f  %7.1f'
              % (d, sg, vl, vr, abs(vl) / d, abs(vr) / d))
        sl += abs(vl) / d; sr += abs(vr) / d; n += 1
    kl, kr = sl / n, sr / n            # [counts/s per % duty]
    fdv_l, fdv_r = kl * 100.0, kr * 100.0
    fdv = 0.5 * (fdv_l + fdv_r)
    print()
    print('  full_duty_velocity  left %.0f  right %.0f  mean %.0f'
          % (fdv_l, fdv_r, fdv))
    # kernel divides command by gain: gain = plant/mean
    print('  wheel_gain_left  %.3f' % (fdv_l / fdv))
    print('  wheel_gain_right %.3f' % (fdv_r / fdv))


if __name__ == '__main__':
    main()
