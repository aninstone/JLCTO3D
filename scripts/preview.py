# -*- coding: utf-8 -*-
"""JLCTO3D 自检工具: 把 STEP 渲染成 PNG(按面颜色, 画家算法) 用来肉眼检查。

用法(必须用 FreeCAD 自带 python.exe, 因为要 import FreeCAD/numpy/PIL):
  python.exe preview.py <源.step> <out.png> [top|iso] [宽] [高] [r,g,b]

  [r,g,b] 可选: 只画该颜色的面(并画成深色), 用来单独看某个特征的形状。
"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import numpy as np
from PIL import Image
import FreeCAD, FreeCADGui, Import

FreeCADGui.setupWithoutGUI()

src = sys.argv[1]
out = sys.argv[2]
mode = sys.argv[3] if len(sys.argv) > 3 else 'top'
W = int(sys.argv[4]) if len(sys.argv) > 4 else 900
H = int(sys.argv[5]) if len(sys.argv) > 5 else 760
ONLY = tuple(float(x) for x in sys.argv[6].split(',')) if len(sys.argv) > 6 else None

doc = FreeCAD.newDocument('d')
items = Import.open(src)

tris = []   # (color, pts2d, depth)
allpts = []
for f, c in items:
    sh = f.Shape
    for i, face in enumerate(sh.Faces):
        col = tuple(c[i]) if i < len(c) else (0.8, 0.8, 0.8, 1.0)
        if ONLY is not None and not all(abs(col[k] - ONLY[k]) <= 0.03 for k in range(3)):
            continue
        try:
            verts, facets = face.tessellate(0.05)
        except Exception:
            continue
        P = np.array([[v.x, v.y, v.z] for v in verts])
        for fa in facets:
            tri = P[list(fa)]
            tris.append((col, tri))
            allpts.append(tri)

A = np.vstack(allpts)
if mode == 'top':
    # project X->right, Y->up
    prj = lambda T: np.stack([T[:, 0], T[:, 1]], axis=1)
    depth = lambda T: T[:, 2].mean()
else:
    # isometric-ish
    c30, s30 = np.cos(np.radians(30)), np.sin(np.radians(30))
    prj = lambda T: np.stack([T[:, 0] * c30 - T[:, 1] * c30, (T[:, 0] + T[:, 1]) * s30 + T[:, 2]], axis=1)
    depth = lambda T: (T[:, 0] + T[:, 1] - T[:, 2]).mean()

P2 = np.vstack([prj(T) for _, T in tris])
xmin, ymin = P2.min(axis=0)
xmax, ymax = P2.max(axis=0)
pad = 0.04 * max(xmax - xmin, ymax - ymin)
xmin -= pad; xmax += pad; ymin -= pad; ymax += pad
sc = min((W - 1) / (xmax - xmin), (H - 1) / (ymax - ymin))
ox = (W - (xmax - xmin) * sc) / 2
oy = (H - (ymax - ymin) * sc) / 2

img = np.ones((H, W, 3), dtype=np.uint8) * 255
order = sorted(range(len(tris)), key=lambda k: depth(tris[k][1]))
for k in order:
    col, T = tris[k]
    p = prj(T)
    px = (p[:, 0] - xmin) * sc + ox
    py = H - 1 - ((p[:, 1] - ymin) * sc + oy)
    x0 = max(int(np.floor(px.min())), 0); x1 = min(int(np.ceil(px.max())), W - 1)
    y0 = max(int(np.floor(py.min())), 0); y1 = min(int(np.ceil(py.max())), H - 1)
    if x1 < x0 or y1 < y0:
        continue
    xs = np.arange(x0, x1 + 1) + 0.5
    ys = np.arange(y0, y1 + 1) + 0.5
    Xg, Yg = np.meshgrid(xs, ys)
    d = np.zeros(Xg.shape, dtype=bool)
    for a in range(3):
        b = (a + 1) % 3
        cx, cy = px[b] - px[a], py[b] - py[a]
        cross = (Xg - px[a]) * cy - (Yg - py[a]) * cx
        d ^= (cross > 0)
    inside = d | d.all()  # degenerate-safe
    inside = d if d.any() else inside
    sub = img[y0:y1 + 1, x0:x1 + 1]
    rgb = np.array([int(255 * col[0]), int(255 * col[1]), int(255 * col[2])], dtype=np.uint8)
    if ONLY is not None:
        rgb = np.array([30, 30, 30], dtype=np.uint8)
    sub[d] = rgb

Image.fromarray(img).save(out)
print('saved', out, 'tris', len(tris))
FreeCAD.closeDocument(doc.Name)
