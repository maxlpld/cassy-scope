#!/usr/bin/env python3
import os, sys, json, datetime, time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Force Tk backend for matplotlib GUI
os.environ.setdefault("MPLBACKEND", "TkAgg")
import matplotlib
matplotlib.use("TkAgg")
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

# pythonnet 3.x: choose Mono runtime before importing clr
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

# Load LD DLLs
Assembly.LoadFrom(join(LIB_DIR, "InTheHand.Net.Personal.dll"))
Assembly.LoadFrom(join(LIB_DIR, "LD.Api.dll"))
from LD.Api import CASSYs  # noqa

# ---------- helpers for fitting ----------
def estimate_freq_fft(t, y):
    if len(t) < 2: return None
    dt = float(np.median(np.diff(t)))
    if dt <= 0: return None
    yf = np.fft.rfft(y - np.mean(y))
    xf = np.fft.rfftfreq(len(y), d=dt)
    if len(xf) < 2: return None
    idx = np.argmax(np.abs(yf[1:])) + 1
    return float(xf[idx])

def sin_model(t, A, B, C, D):  # A·sin(2π·B·t + C) + D
    return A * np.sin(2*np.pi*B*t + C) + D

def linear_fit_fixed_freq(t, y, freq):
    w = 2*np.pi*freq
    S = np.sin(w*t); Cc = np.cos(w*t)
    M = np.column_stack([S, Cc, np.ones_like(t)])
    coeffs, *_ = np.linalg.lstsq(M, y, rcond=None)
    a, b, d = coeffs
    A = float((a*a + b*b)**0.5)
    phase = np.arctan2(b, a)
    return A, freq, float(phase), float(d)

def safe_curve_fit(t, y, p0):
    try:
        from scipy.optimize import curve_fit
        popt, _ = curve_fit(sin_model, t, y, p0=p0, maxfev=20000)
        return tuple(map(float, popt)), True
    except Exception:
        A0, B0, C0, D0 = p0
        if not B0:
            span = max(t) - min(t) + 1e-6
            B0 = estimate_freq_fft(t, y) or 1.0/span
        Bs = np.linspace(0.8*B0, 1.2*B0, 41)
        best = None
        for B in Bs:
            A, _, C, D = linear_fit_fixed_freq(t, y, B)
            yhat = sin_model(t, A, B, C, D)
            err = float(np.mean((y - yhat)**2))
            if (best is None) or (err < best[0]):
                best = (err, (A, B, C, D))
        return best[1], False

# ---------- acquisition ----------
def _quantity_values(qobj, length_hint=None):
    # Try length-aware getters first
    for name in ("GetValues", "GetOscilloscopeValues"):
        if hasattr(qobj, name):
            try:
                if length_hint is not None:
                    return list(getattr(qobj, name)(int(length_hint)))
            except Exception:
                pass
    # Fallback: no-arg getters
    for name in ("GetValues", "GetOscilloscopeValues"):
        if hasattr(qobj, name):
            try:
                return list(getattr(qobj, name)())
            except Exception:
                pass
    # Fallback: exposed collections
    for name in ("Values", "OscilloscopeValues", "Samples", "Data"):
        if hasattr(qobj, name):
            try:
                return list(getattr(qobj, name))
            except Exception:
                pass
    return None

def acquire_once(dt, count, channel="A", quantity="U", trigger=False,
                 trig_value=0.0, trig_edge="rising", pretrigger=0, range_index=None,
                 timeout_s=30.0, progress_cb=None):
    """
    One-shot capture. Calls progress_cb(frac: 0..1) regularly.
    """
    import glob
    cs = CASSYs()
    tried = []
    try:
        cs.EnableDeviceChangedEvents = False

        # Prefer exact node (/dev/ldusb0), then autoscan, then common nodes
        try:
            cs.CommPort = "/dev/ldusb0"; tried.append("/dev/ldusb0")
            time.sleep(0.25); cs.Scan()
        except Exception:
            pass
        if cs.Count == 0:
            try:
                cs.CommPort = ""; tried.append("<auto-scan>")
                time.sleep(0.10); cs.Scan()
            except Exception:
                pass
        if cs.Count == 0:
            for devnode in (glob.glob("/dev/ttyACM*") + glob.glob("/dev/ldusb*")):
                tried.append(devnode)
                if not os.path.exists(devnode): continue
                try:
                    cs.CommPort = devnode
                    time.sleep(0.10); cs.Scan()
                    if cs.Count > 0: break
                except Exception:
                    continue
        if cs.Count == 0:
            raise RuntimeError("No CASSY module found. Tried: " + ", ".join(tried))

        # Device + IO
        try:
            dev = cs[0]
        except Exception:
            dev = list(cs.Items)[0]
        ios = cs.CASSYIOs
        ab = 0 if str(channel).upper() == "A" else 1
        try:
            io = ios.get_Item(dev, ab, True)
        except Exception:
            io = ios.get_Item(dev, ab, False)

        # Quantity & optional range
        q = str(quantity).upper()
        if q == "U":
            io.QuantityU.Selected = True; qobj = io.QuantityU
            if range_index not in (None, ""):
                io.QuantityU.RangeIndex = int(range_index)
        elif q == "I":
            io.QuantityI.Selected = True; qobj = io.QuantityI
            if range_index not in (None, ""):
                io.QuantityI.RangeIndex = int(range_index)
        else:
            raise ValueError("quantity must be U or I")

        # Prefer fast if dt < slow minimum
        min_slow = getattr(ios, "MinimumSlowOscilloscopeInterval", 0.1)
        if dt < float(min_slow) and hasattr(ios, "PreferSlowOscilloscope"):
            try: ios.PreferSlowOscilloscope = False
            except Exception: pass

        # Configure
        if hasattr(ios, "OscilloscopeInterval"): ios.OscilloscopeInterval = float(dt)
        if hasattr(ios, "OscilloscopeCount"):    ios.OscilloscopeCount    = int(count)

        # No trigger (your workflow)
        for target in (ios, io):
            if hasattr(target, "Trigger"):
                try: setattr(target, "Trigger", False)
                except: pass
            if hasattr(target, "PretriggerCount"):
                try: setattr(target, "PretriggerCount", 0)
                except: pass

        # Start
        if hasattr(ios, "StartOscilloscope"):
            try: ios.StartOscilloscope()
            except Exception: pass

        expected_time = float(dt) * int(count)
        hard_timeout  = max(timeout_s, expected_time + 5.0)
        t0 = time.time()
        t_list, y_list = [], None

        # initial progress 0
        if callable(progress_cb):
            try: progress_cb(0.0)
            except Exception: pass

        while (time.time() - t0) < hard_timeout:
            done_flag = False
            if hasattr(ios, "DoOscilloscope"):
                try:
                    r = ios.DoOscilloscope()
                    try: done_flag = bool(r)
                    except Exception: pass
                except Exception:
                    pass

            # read times
            got_times = False
            if hasattr(ios, "GetTimes"):
                try:
                    t_list = list(ios.GetTimes(int(count))); got_times = True
                except Exception:
                    try:
                        t_list = list(ios.GetTimes()); got_times = True
                    except Exception:
                        pass
            if not got_times and hasattr(ios, "Times"):
                try:
                    t_list = list(getattr(ios, "Times")); got_times = True
                except Exception:
                    pass

            # progress update
            if callable(progress_cb):
                try:
                    if got_times and t_list:
                        frac = min(1.0, len(t_list)/max(1, int(count)))
                    else:
                        frac = min(1.0, (time.time()-t0)/max(0.001, expected_time))
                    progress_cb(frac)
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

        if not t_list:
            raise RuntimeError("Could not read time vector from device.")
        if y_list is None or len(y_list) != len(t_list):
            raise RuntimeError(f"Incomplete capture (t={len(t_list)}, y={0 if y_list is None else len(y_list)}).")

        # Rebase to start at 0 s
        t_np = np.array(t_list, float)
        t_np -= float(np.min(t_np))
        y_np = np.array(y_list, float)

        # final progress 100%
        if callable(progress_cb):
            try: progress_cb(1.0)
            except Exception: pass

        legend = [f"{quantity}({channel})"]
        return t_np, y_np, {"legend": legend, "tried": tried}

    finally:
        try: cs.Dispose()
        except Exception: pass

# ---------- GUI ----------
class CassyApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CASSY Scope")
        self.geometry("980x680")

        # Make GNOME dock use our icon
        try:
            self.wm_class("cassy-scope", "CASSY Scope")
        except Exception:
            pass
        try:
            icon_file = os.path.join(BASE_DIR, "cassy-logo.png")
            if os.path.exists(icon_file):
                self.iconphoto(True, tk.PhotoImage(file=icon_file))
        except Exception:
            pass

        # Controls
        self.var_channel  = tk.StringVar(value="A")
        self.var_quantity = tk.StringVar(value="U")
        self.var_dt_ms    = tk.StringVar(value="1.0")
        self.var_count    = tk.StringVar(value="20001")
        self.var_trigger  = tk.BooleanVar(value=False)
        self.var_trig_val = tk.StringVar(value="0.0")
        self.var_trig_edge= tk.StringVar(value="rising")
        self.var_pretrig  = tk.StringVar(value="0")
        self.var_rangeidx = tk.StringVar(value="")
        self.var_A0 = tk.StringVar(value=""); self.var_B0 = tk.StringVar(value="")
        self.var_C0 = tk.StringVar(value=""); self.var_D0 = tk.StringVar(value="")

        self.t = None; self.y = None; self.last_meta = {}
        self.amp_text = None; self.fit_line = None

        self._build_ui()

    # --- UI ---
    def _build_ui(self):
        top = ttk.Frame(self); top.pack(side=tk.TOP, fill=tk.X, padx=6, pady=6)

        # Settings panel
        cfg = ttk.Labelframe(top, text="Settings"); cfg.pack(side=tk.LEFT, fill=tk.Y, padx=6)
        row = 0
        ttk.Label(cfg, text="Channel").grid(row=row, column=0, sticky="w")
        ttk.Combobox(cfg, textvariable=self.var_channel, values=("A","B"), width=6, state="readonly").grid(row=row, column=1, padx=4, pady=2); row+=1

        ttk.Label(cfg, text="Quantity").grid(row=row, column=0, sticky="w")
        qbox = ttk.Combobox(cfg, textvariable=self.var_quantity, values=("U","I"), width=6, state="readonly")
        qbox.grid(row=row, column=1, padx=4, pady=2)
        qbox.bind("<<ComboboxSelected>>", lambda e: self._on_quantity_changed())
        self.var_quantity.trace_add("write", lambda *_: self._on_quantity_changed()); row+=1

        ttk.Label(cfg, text="dt (ms)").grid(row=row, column=0, sticky="w")
        ttk.Entry(cfg, textvariable=self.var_dt_ms, width=8).grid(row=row, column=1, padx=4, pady=2); row+=1
        ttk.Label(cfg, text="# samples").grid(row=row, column=0, sticky="w")
        ttk.Entry(cfg, textvariable=self.var_count, width=10).grid(row=row, column=1, padx=4, pady=2); row+=1
        ttk.Label(cfg, text="RangeIndex").grid(row=row, column=0, sticky="w")
        ttk.Entry(cfg, textvariable=self.var_rangeidx, width=8).grid(row=row, column=1, padx=4, pady=2); row+=1

        ttk.Separator(cfg).grid(row=row, column=0, columnspan=2, sticky="ew", pady=4); row+=1
        ttk.Checkbutton(cfg, text="Trigger", variable=self.var_trigger).grid(row=row, column=0, sticky="w"); row+=1
        ttk.Label(cfg, text="Threshold").grid(row=row, column=0, sticky="w")
        ttk.Entry(cfg, textvariable=self.var_trig_val, width=8).grid(row=row, column=1, padx=4, pady=2); row+=1
        ttk.Label(cfg, text="Edge").grid(row=row, column=0, sticky="w")
        ttk.Combobox(cfg, textvariable=self.var_trig_edge, values=("rising","falling"), width=8, state="readonly").grid(row=row, column=1, padx=4, pady=2); row+=1
        ttk.Label(cfg, text="Pretrigger").grid(row=row, column=0, sticky="w")
        ttk.Entry(cfg, textvariable=self.var_pretrig, width=8).grid(row=row, column=1, padx=4, pady=2)

        # Actions panel (with progress bar)
        btns = ttk.Labelframe(top, text="Actions"); btns.pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(btns, text="Start measurement", command=self.on_measure).pack(fill=tk.X, padx=6, pady=4)
        ttk.Button(btns, text="Measure amplitude", command=self.on_amplitude).pack(fill=tk.X, padx=6, pady=4)
        ttk.Button(btns, text="Sine fit (A,B,C,D)", command=self.on_fit).pack(fill=tk.X, padx=6, pady=4)
        ttk.Button(btns, text="Save data (CSV)",   command=self.on_save_csv).pack(fill=tk.X, padx=6, pady=4)
        ttk.Button(btns, text="Save plot (PNG)",   command=self.on_save_png).pack(fill=tk.X, padx=6, pady=4)

        ttk.Label(btns, text="Progress").pack(anchor="w", padx=6, pady=(8,0))
        self.progress = ttk.Progressbar(btns, orient="horizontal", mode="determinate", maximum=100)
        self.progress.pack(fill=tk.X, padx=6, pady=(2,8))

        # Fit parameters panel (restored)
        params = ttk.Labelframe(top, text="Fit parameters (optional)"); params.pack(side=tk.LEFT, fill=tk.Y, padx=6)
        for i,(lab,var) in enumerate([("A0",self.var_A0),("B0 (Hz)",self.var_B0),("C0 (rad)",self.var_C0),("D0",self.var_D0)]):
            ttk.Label(params, text=lab).grid(row=i, column=0, sticky="w")
            ttk.Entry(params, textvariable=var, width=10).grid(row=i, column=1, padx=4, pady=2)

        # Plot
        fig = plt.Figure(figsize=(6.5,4.6), dpi=100)
        self.ax = fig.add_subplot(111)
        self.ax.set_xlabel("t (s)"); self.ax.set_ylabel(self._ylabel()); self.ax.grid(True)
        self.canvas = FigureCanvasTkAgg(fig, master=self)
        self.canvas.draw(); self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        NavigationToolbar2Tk(self.canvas, self)

        # Status line
        self.status = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status, relief=tk.SUNKEN, anchor="w").pack(fill=tk.X, side=tk.BOTTOM)

    # --- small helpers ---
    def _ylabel(self):
        return "U (V)" if self.var_quantity.get().upper()=="U" else "I (A)"

    def _on_quantity_changed(self):
        self.ax.set_ylabel(self._ylabel()); self.canvas.draw_idle()

    def _set_progress(self, frac):
        try:
            frac = max(0.0, min(1.0, float(frac)))
            self.progress["value"] = int(frac*100)
            self.update_idletasks()  # ensure the bar animates during capture
        except Exception:
            pass

    # --- actions ---
    def on_measure(self):
        try:
            dt_s = float(self.var_dt_ms.get())/1000.0
            count = int(self.var_count.get())
            rng = int(self.var_rangeidx.get()) if self.var_rangeidx.get().strip()!="" else None
            trig = bool(self.var_trigger.get())
            trig_val = float(self.var_trig_val.get())
            trig_edge= self.var_trig_edge.get()
            pretrig = int(self.var_pretrig.get())
        except Exception as e:
            messagebox.showerror("Invalid parameters", str(e)); return

        # start progress
        self._set_progress(0.0)
        self.status.set("Capturing…"); self.update_idletasks()

        try:
            t, y, meta = acquire_once(
                dt=dt_s, count=count,
                channel=self.var_channel.get(), quantity=self.var_quantity.get(),
                trigger=trig, trig_value=trig_val, trig_edge=trig_edge,
                pretrigger=pretrig, range_index=rng,
                progress_cb=self._set_progress
            )
        except Exception as e:
            self._set_progress(0.0)
            messagebox.showwarning("Acquisition failed", str(e))
            self.status.set("Failed.")
            return

        self._set_progress(100.0)
        self.t, self.y, self.last_meta = t, y, meta
        self._plot_data()

        # suggest starting fit params
        try:
            A0 = 0.5*(np.max(y)-np.min(y)); self.var_A0.set(f"{A0:.6g}")
            B0 = estimate_freq_fft(t,y) or 0.0; self.var_B0.set(f"{B0:.6g}")
            self.var_C0.set("0.0"); self.var_D0.set(f"{float(np.mean(y)):.6g}")
        except Exception:
            pass
        self.status.set(f"Capture OK: {len(y)} samples, dt={self.var_dt_ms.get()} ms.")

    def _plot_data(self):
        self.ax.clear(); self.ax.grid(True)
        self.ax.set_xlabel("t (s)"); self.ax.set_ylabel(self._ylabel())
        if self.t is not None and self.y is not None:
            self.ax.plot(self.t, self.y, label="signal")
            ylo, yhi = float(np.min(self.y)), float(np.max(self.y))
            pad = 0.05*(yhi - ylo + 1e-12)
            self.ax.set_ylim(ylo - pad, yhi + pad)
            self.ax.legend(loc="upper right")  # avoid overlap with amplitude text at top-left
        self.canvas.draw_idle()

    def on_amplitude(self):
        if self.y is None:
            messagebox.showinfo("Amplitude", "No data yet. Start a measurement first."); return
        A = 0.5*(float(np.max(self.y)) - float(np.min(self.y)))
        unit = "V" if self.var_quantity.get().upper()=="U" else "A"
        if self.amp_text:
            try: self.amp_text.remove()
            except Exception: pass
        txt = f"Amplitude ≈ {A:.6g} {unit}"
        self.amp_text = self.ax.text(0.02, 0.95, txt, transform=self.ax.transAxes,
                                     ha="left", va="top",
                                     bbox=dict(boxstyle="round", fc="w", ec="0.7"))
        self.ax.legend(loc="upper right"); self.canvas.draw_idle(); self.status.set(txt)

    def on_fit(self):
        if self.t is None or self.y is None:
            messagebox.showinfo("Sine fit", "No data yet. Start a measurement first."); return
        def parse(v, default):
            s=v.strip(); return float(s) if s!="" else default
        A0 = parse(self.var_A0.get(), 0.5*(np.max(self.y)-np.min(self.y)))
        B0 = parse(self.var_B0.get(), estimate_freq_fft(self.t,self.y) or 0.0)
        C0 = parse(self.var_C0.get(), 0.0)
        D0 = parse(self.var_D0.get(), float(np.mean(self.y)))
        (A,B,C,D), used_scipy = safe_curve_fit(self.t, self.y, (A0,B0,C0,D0))
        yhat = sin_model(self.t, A,B,C,D)
        if self.fit_line:
            try: self.fit_line.remove()
            except Exception: pass
        (self.fit_line,) = self.ax.plot(self.t, yhat, linestyle="--",
                                        label=f"fit: A={A:.3g}, B={B:.3g} Hz")
        self.ax.legend(loc="upper right"); self.canvas.draw_idle()
        self.status.set(f"Fit {'(SciPy)' if used_scipy else '(approx)'}: "
                        f"A={A:.6g}, B={B:.6g} Hz, C={C:.6g} rad, D={D:.6g}")

    def _suggest_folder(self):
        d = os.path.join(os.path.expanduser("~"), "CASSY")
        os.makedirs(d, exist_ok=True)
        return d

    def on_save_csv(self):
        if self.t is None or self.y is None:
            messagebox.showinfo("Save", "No data to save."); return
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default = os.path.join(self._suggest_folder(), f"cassy_capture_{ts}.csv")
        path = filedialog.asksaveasfilename(title="Save data (CSV)", defaultextension=".csv",
                                            filetypes=[("CSV","*.csv")],
                                            initialfile=os.path.basename(default),
                                            initialdir=os.path.dirname(default))
        if not path: return
        data = np.column_stack([self.t, self.y])
        np.savetxt(path, data, delimiter=",", header="t,y", comments="")
        try:
            meta = {"dt": float(np.median(np.diff(self.t))), "count": int(len(self.t)),
                    "quantity": self.var_quantity.get(), "channel": self.var_channel.get()}
            with open(path.replace(".csv",".json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
        except Exception:
            pass
        self.status.set(f"Data saved: {path}")

    def on_save_png(self):
        if self.t is None or self.y is None:
            messagebox.showinfo("Save", "No data to save."); return
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default = os.path.join(self._suggest_folder(), f"cassy_capture_{ts}.png")
        path = filedialog.asksaveasfilename(title="Save plot (PNG)", defaultextension=".png",
                                            filetypes=[("PNG","*.png")],
                                            initialfile=os.path.basename(default),
                                            initialdir=os.path.dirname(default))
        if not path: return
        self.ax.legend(loc="upper right"); self.canvas.draw()
        self.canvas.figure.savefig(path, dpi=150, bbox_inches="tight")
        self.status.set(f"Plot saved: {path}")

if __name__ == "__main__":
    CassyApp().mainloop()

