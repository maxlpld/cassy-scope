#!/usr/bin/env python3
# Robust scan + capture for your LD.Api build (pythonnet 3.x, Mono).
from clr_loader import get_mono
from pythonnet import set_runtime
set_runtime(get_mono())

import time
import clr
from System.Reflection import Assembly

# Load vendor DLLs
Assembly.LoadFrom("/opt/cassy/lib/InTheHand.Net.Personal.dll")
Assembly.LoadFrom("/opt/cassy/lib/LD.Api.dll")
from LD.Api import CASSYs  # noqa


def list_members(obj, title=None, needles=("Osc", "Scope", "Value", "Times", "Count", "Message", "Error")):
    try:
        t = obj.GetType()
        if title:
            print(f"\n=== {title} ({t.FullName}) ===")
        else:
            print(f"\n=== Members of {t.FullName} ===")
        for p in t.GetProperties():
            n = p.Name
            if any(k.lower() in n.lower() for k in needles):
                try:
                    v = p.GetValue(obj, None)
                except Exception:
                    v = "<unreadable>"
                print(f"  [prop] {n} = {v}")
        for m in t.GetMethods():
            n = m.Name
            if any(k.lower() in n.lower() for k in needles):
                try:
                    params = [str(pi.ParameterType.Name) for pi in m.GetParameters()]
                except Exception:
                    params = ["?"]
                print(f"  (meth) {n}({', '.join(params)})")
    except Exception as e:
        print("Member listing failed:", e)


def quantity_get_values(qobj, length_hint=None):
    """
    Return list of values from the quantity object (QuantityU / QuantityI),
    trying the variants this DLL might expose.
    """
    # Try method with length
    for name in ("GetValues", "GetOscilloscopeValues"):
        if hasattr(qobj, name):
            try:
                if length_hint is not None:
                    res = getattr(qobj, name)(int(length_hint))
                    return list(res)
            except Exception:
                pass
    # Try method without args
    for name in ("GetValues", "GetOscilloscopeValues"):
        if hasattr(qobj, name):
            try:
                res = getattr(qobj, name)()
                # res can be iterable
                return list(res)
            except Exception:
                pass
    # Try property
    for name in ("Values", "OscilloscopeValues", "Samples", "Data"):
        if hasattr(qobj, name):
            try:
                res = getattr(qobj, name)
                return list(res)
            except Exception:
                pass
    return None


def main(dt=0.001, count=2001, channel="A", quantity="U"):
    cs = CASSYs()
    cs.EnableDeviceChangedEvents = False

    # Prefer your known node
    cs.CommPort = "/dev/ldusb0"
    time.sleep(0.25)
    cs.Scan()
    print("Count after /dev/ldusb0:", cs.Count)

    if cs.Count == 0:
        cs.CommPort = ""
        cs.Scan()
        print("Count after autoscan:", cs.Count)

    assert cs.Count > 0, "No device detected"

    # First device
    try:
        dev = cs[0]
    except Exception:
        items = list(cs.Items)
        if not items:
            raise RuntimeError("Scan returned no devices (Items empty).")
        dev = items[0]

    ios = cs.CASSYIOs
    ab = 0 if str(channel).upper() == "A" else 1

    # Get IO (boxed input for Sensor-CASSY 2). If that fails, use plain.
    try:
        io = ios.get_Item(dev, ab, True)
    except Exception:
        io = ios.get_Item(dev, ab, False)

    # Select quantity
    q = str(quantity).upper()
    if q == "U":
        io.QuantityU.Selected = True
        qobj = io.QuantityU
    elif q == "I":
        io.QuantityI.Selected = True
        qobj = io.QuantityI
    else:
        raise ValueError("quantity must be 'U' or 'I'")

    # Configure oscilloscope on ios (preferred) and io (fallback)
    min_slow = getattr(ios, "MinimumSlowOscilloscopeInterval", 0.1)
    prefer_slow = getattr(ios, "PreferSlowOscilloscope", True)

    # If asking for dt < slow minimum, prefer fast mode
    if dt < float(min_slow) and prefer_slow and hasattr(ios, "PreferSlowOscilloscope"):
        try:
            ios.PreferSlowOscilloscope = False
            print(f"PreferSlowOscilloscope -> False (fast mode) because dt={dt} < {min_slow}")
        except Exception:
            pass

    # Set interval & count (try ios, then io)
    set_ok = False
    for target in (ios, io):
        ok1 = hasattr(target, "OscilloscopeInterval")
        ok2 = hasattr(target, "OscilloscopeCount")
        if ok1:
            setattr(target, "OscilloscopeInterval", float(dt))
        if ok2:
            setattr(target, "OscilloscopeCount", int(count))
        set_ok = set_ok or (ok1 and ok2)

    # Optional trigger off
    for target in (ios, io):
        if hasattr(target, "Trigger"):
            try:
                setattr(target, "Trigger", False)
            except Exception:
                pass
        if hasattr(target, "PretriggerCount"):
            try:
                setattr(target, "PretriggerCount", 0)
            except Exception:
                pass

    # Show what the objects expose (first time)
    print("\n--- Introspection (CASSYIOs) ---")
    list_members(ios)
    print("\n--- Introspection (Quantity) ---")
    list_members(qobj, title="Selected Quantity")

    # Start the measurement
    started = False
    for obj in (ios, io):
        if hasattr(obj, "StartOscilloscope"):
            try:
                obj.StartOscilloscope()
                started = True
                break
            except Exception:
                pass
    # It also works to simply poll DoOscilloscope without Start*; we'll do both.
    t_list = []
    y_list = None
    t0 = time.time()
    timeout_s = 5.0

    while (time.time() - t0) < timeout_s:
        # progress one step
        did = False
        for obj in (ios, io):
            if hasattr(obj, "DoOscilloscope"):
                try:
                    _ = obj.DoOscilloscope()
                    did = True
                    break
                except Exception:
                    pass

        # read times (prefer ios.GetTimes())
        times_read = False
        if hasattr(ios, "GetTimes"):
            try:
                # First try without length (many builds support that)
                t_list = list(ios.GetTimes())
                times_read = True
            except Exception:
                # Try with length (use OscilloscopeCount as hint if set)
                try:
                    t_list = list(ios.GetTimes(int(count)))
                    times_read = True
                except Exception:
                    pass

        # If times still unread, try property Times
        if not times_read and hasattr(ios, "Times"):
            try:
                t_list = list(getattr(ios, "Times"))
                times_read = True
            except Exception:
                pass

        # If we have times, try to read values from the quantity object
        if times_read and t_list:
            y_list = quantity_get_values(qobj, length_hint=len(t_list))
            if y_list is not None and len(y_list) == len(t_list):
                break

        time.sleep(0.01)

    # Stop oscilloscope if method exists
    for obj in (ios, io):
        if hasattr(obj, "StopOscilloscope"):
            try:
                obj.StopOscilloscope()
                break
            except Exception:
                pass

    if not t_list:
        raise RuntimeError("Could not read times from CASSYIOs (neither GetTimes() nor Times property worked).")
    if y_list is None:
        raise RuntimeError("Could not read values from the selected Quantity (no GetValues/Values variant worked).")
    if len(y_list) != len(t_list):
        raise RuntimeError(f"Times/Values length mismatch: len(t)={len(t_list)}, len(y)={len(y_list)}")

    print("\nSuccess!")
    print("Length:", len(t_list))
    print("First samples t:", t_list[:5])
    print("First samples y:", y_list[:5])

    cs.Dispose()


if __name__ == "__main__":
    # dt=0.001 fast mode; increase to 0.1 if you want slow mode explicitly
    main(dt=0.001, count=2001, channel="A", quantity="U")

