#!/usr/bin/env python3
import os, argparse, datetime, time
import numpy as np

# choose Mono runtime before importing clr
try:
    from clr_loader import get_mono
    from pythonnet import set_runtime
    set_runtime(get_mono())
except Exception:
    pass

import clr
from System.Reflection import Assembly
from os.path import join, dirname, abspath
BASE_DIR = abspath(dirname(__file__))
LIB_DIR  = join(BASE_DIR, "lib")
Assembly.LoadFrom(join(LIB_DIR, "InTheHand.Net.Personal.dll"))
Assembly.LoadFrom(join(LIB_DIR, "LD.Api.dll"))
from LD.Api import CASSYs  # noqa

def _quantity_values(qobj, length_hint=None):
    for name in ("GetValues", "GetOscilloscopeValues"):
        if hasattr(qobj, name):
            try:
                if length_hint is not None:
                    return list(getattr(qobj, name)(int(length_hint)))
            except Exception:
                pass
    for name in ("GetValues", "GetOscilloscopeValues"):
        if hasattr(qobj, name):
            try:
                return list(getattr(qobj, name)())
            except Exception:
                pass
    for name in ("Values", "OscilloscopeValues", "Samples", "Data"):
        if hasattr(qobj, name):
            try:
                return list(getattr(qobj, name))
            except Exception:
                pass
    return None

def capture(dt=0.001, count=20001, channel="A", quantity="U", timeout_s=30.0):
    cs = CASSYs()
    cs.EnableDeviceChangedEvents = False
    tried = []

    # open device
    cs.CommPort = "/dev/ldusb0"; tried.append("/dev/ldusb0")
    time.sleep(0.25); cs.Scan()
    if cs.Count == 0:
        cs.CommPort = ""; tried.append("<auto-scan>"); cs.Scan()
    if cs.Count == 0:
        raise RuntimeError("No CASSY device (tried: " + ", ".join(tried) + ")")

    # device + IO
    try:
        dev = cs[0]
    except Exception:
        dev = list(cs.Items)[0]
    ios = cs.CASSYIOs
    ab = 0 if str(channel).upper()=="A" else 1
    try:
        io = ios.get_Item(dev, ab, True)
    except Exception:
        io = ios.get_Item(dev, ab, False)

    # quantity
    if str(quantity).upper()=="U":
        io.QuantityU.Selected=True; qobj = io.QuantityU
    else:
        io.QuantityI.Selected=True; qobj = io.QuantityI

    # fast vs slow
    min_slow = getattr(ios, "MinimumSlowOscilloscopeInterval", 0.1)
    if dt < float(min_slow) and hasattr(ios, "PreferSlowOscilloscope"):
        try: ios.PreferSlowOscilloscope = False
        except Exception: pass

    # configure
    if hasattr(ios, "OscilloscopeInterval"): ios.OscilloscopeInterval=float(dt)
    if hasattr(ios, "OscilloscopeCount"):    ios.OscilloscopeCount=int(count)
    for target in (ios, io):
        if hasattr(target, "Trigger"):
            try: setattr(target, "Trigger", False)
            except Exception: pass
        if hasattr(target, "PretriggerCount"):
            try: setattr(target, "PretriggerCount", 0)
            except Exception: pass

    # start
    if hasattr(ios, "StartOscilloscope"):
        try: ios.StartOscilloscope()
        except Exception: pass

    expected_time = float(dt)*int(count)
    hard_timeout  = max(timeout_s, expected_time + 5.0)
    t0 = time.time()
    t_list, y_list = [], None

    while (time.time() - t0) < hard_timeout:
        done_flag = False
        if hasattr(ios, "DoOscilloscope"):
            try:
                r = ios.DoOscilloscope()
                try: done_flag = bool(r)
                except Exception: pass
            except Exception: pass

        got_times = False
        if hasattr(ios, "GetTimes"):
            try:
                t_list = list(ios.GetTimes(int(count)))
                got_times = True
            except Exception:
                try:
                    t_list = list(ios.GetTimes())
                    got_times = True
                except Exception:
                    pass
        if not got_times and hasattr(ios, "Times"):
            try:
                t_list = list(getattr(ios, "Times")); got_times = True
            except Exception:
                pass

        enough  = got_times and (len(t_list) >= int(0.98*int(count)))
        status  = str(getattr(ios, "OscilloscopeStatus", ""))
        stopped = ("Stopped" in status)

        if (done_flag or enough or stopped or (time.time() - t0) >= expected_time):
            if got_times and t_list and y_list is None:
                y_list = _quantity_values(qobj, len(t_list))
            if y_list is not None and len(y_list) == len(t_list):
                break

        time.sleep(0.01)

    if hasattr(ios, "StopOscilloscope"):
        try: ios.StopOscilloscope()
        except Exception: pass

    cs.Dispose()
    if not t_list or y_list is None:
        raise RuntimeError("No data received")
    if len(y_list) != len(t_list):
        raise RuntimeError(f"Times/Values mismatch: t={len(t_list)}, y={len(y_list)}")

    t = np.array(t_list, float); t -= float(np.min(t))
    y = np.array(y_list, float)
    return t, y

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dt", type=float, default=0.001)
    ap.add_argument("--count", type=int, default=20001)
    ap.add_argument("--quantity", choices=["U","I"], default="U")
    ap.add_argument("--channel", choices=["A","B"], default="A")
    ap.add_argument("--outdir", default=None)
    args = ap.parse_args()

    t, y = capture(dt=args.dt, count=args.count, channel=args.channel, quantity=args.quantity)
    outdir = args.outdir or os.path.join(os.path.expanduser("~"), "CASSY")
    os.makedirs(outdir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_csv = os.path.join(outdir, f"cassy_capture_{ts}.csv")
    np.savetxt(out_csv, np.column_stack([t,y]), delimiter=",", header="t,y", comments="")
    print("Saved", out_csv)

