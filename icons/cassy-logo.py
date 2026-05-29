import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

fig = plt.figure(figsize=(2.56, 2.56), dpi=100)  # 256x256
ax = fig.add_axes([0,0,1,1])
ax.set_axis_off()
# Background
ax.set_facecolor("white")
# Draw a light grid-like frame
ax.plot([0.05,0.95,0.95,0.05,0.05],[0.1,0.1,0.9,0.9,0.1], linewidth=3)
# Sine wave
x = np.linspace(0.1, 0.9, 400)
y = 0.5*np.sin(2*np.pi*2*(x-0.1)) * 0.25 + 0.5
ax.plot(x, y, linewidth=5)
# Title text
ax.text(0.5, 0.82, "CASSY", ha="center", va="center", fontsize=26, weight="bold")
ax.text(0.5, 0.2, "Scope", ha="center", va="center", fontsize=20)
icon_path = icons_dir / "cassy-logo.png"
fig.savefig(icon_path, dpi=100, bbox_inches="tight", pad_inches=0)
plt.close(fig)

