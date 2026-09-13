# -*- coding: utf-8 -*-
"""
JLCTO3D - 从「含 PCB 的嘉立创 EDA 导出 STEP」中自动提取干净单器件封装（保留原始颜色）。

特点:
  1. 自动识别器件对象(无需手动给前缀)；
  2. 剔除 PCB 板 / 丝印字母薄片；
  3. 去重(同一器件多份幽灵副本)；
  4. 居中后导出 STEP，并保留原 STEP 里的面颜色(黑本体/蓝壳/镀金引脚等)。

原理:
  FreeCAD 无头 Import.open() 会返回每个对象及其「逐面颜色列表」，但写入
  STEP 必须调用 GUI 版 ImportGui.export()，且需要 ViewObject。
  所以这里用 QT_QPA_PLATFORM=offscreen 启动一个「看不见的主窗口」，
  让 ViewObject 存在 → 把颜色灌进 DiffuseColor → ImportGui 导出即带色。

用法 (FreeCAD 的 python.exe 运行):
  jlc_extract.py <源.step> <输出.step>
"""
import os
import sys

# 必须在 Qt / FreeCADGui 加载之前设置：开一个「离屏(offscreen)」主窗口，
# 这样 ViewObject 才存在(ImportGui 导出带色必需)，同时屏幕上不会闪窗口。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import FreeCAD  # noqa: E402
import Import   # noqa: E402
import Part     # noqa: E402

src = sys.argv[1]
out = sys.argv[2]

# 排除词: 这些 label 的是 PCB 板 / 丝印 / 文字，不是器件
EXCLUDE = ("board", "pcb", "easyeda", "silk", "text", "footprint",
           "hole", "via", "pad", "annotation", "dimension", "net", "coord",
           "sample")


def obj_volume(o):
    sh = getattr(o, "Shape", None)
    if not sh or sh.isNull():
        return 0.0
    return sum(s.Volume for s in sh.Solids if s.Volume > 0.001)


def strip_logo_decals(shape, colors):
    """剔除嘉立创 EDA 打在外壳上的水印 logo(云图标 + LCEDA / EasyEDA 字样)。

    这类标记在 STEP 里既不是 "silkscreen" 对象、也不在器件本体上，而是被拆成
    若干「独立的零体积平面装饰块」贴在器件外壳表面(典型 13 片: 图标 + 2 行字)。
    判据(同时满足):
      * 厚度 ≈ 0 (Z 向 ≤ 0.02mm) 且 体积 ≈ 0 (≤ 0.02 mm^3) —— 纯平面贴片
      * 该 solid 的所有面颜色都很亮(每通道 >= 0.8) —— 白色丝印
      * 这样的 solid 至少 2 片 —— 字样一定是多片，单片的(如 1 脚标记)不动
    返回 (新shape, 新颜色列表, 删除片数)；无命中时原样返回。
    """
    solids = list(shape.Solids)
    if not solids:
        return shape, colors, 0
    owner = []
    for si, s in enumerate(solids):
        owner.extend([si] * len(s.Faces))
    if len(owner) != len(shape.Faces) or len(colors) != len(shape.Faces):
        return shape, colors, 0

    keep_solids, keep_cols, dropped_labels = [], [], []
    cursor = 0
    for si, s in enumerate(solids):
        n = len(s.Faces)
        fcols = list(colors[cursor:cursor + n])
        cursor += n
        bb = s.BoundBox
        flat = (bb.ZLength <= 0.02) and (s.Volume <= 0.02)
        bright = bool(fcols) and all(
            min(c[0], c[1], c[2]) >= 0.8 for c in fcols)
        if flat and bright:
            dropped_labels.append(
                "S%d(x%.2f..%.2f,y%.2f..%.2f,z%.2f..%.2f,%d面)"
                % (si, bb.XMin, bb.XMax, bb.YMin, bb.YMax, bb.ZMin, bb.ZMax, n))
            continue
        keep_solids.append(s)
        keep_cols.extend(fcols)

    if len(dropped_labels) < 2 or not keep_solids:
        return shape, colors, 0
    print("[INFO] 剔除 EasyEDA 水印贴片 %d 片: %s"
          % (len(dropped_labels), "; ".join(dropped_labels[:16])))
    return Part.makeCompound(keep_solids), keep_cols, len(dropped_labels)


def strip_engraved_text(shape, colors):
    """抹掉 EasyEDA 刻在本体表面的「型号/封装名字」(如 SOIC16)。

    这种字是直接刻进本体的凹槽(深约 0.01mm)，不是独立薄片，删不掉也不能布尔补面。
    但它之所以看得见，只是因为槽壁/槽底被上了亮色 —— 把这几片面的颜色改成
    本体主色，字就「隐形」了(几何仍在，深度 10µm，渲染/打印无影响)。
    判据: 位于外壳顶面/底面的 0.03mm 薄层内 + 比本体亮(每通道>=0.6) + 在 XY 上
    分成 >=4 个独立小块(文字特征) → 判为文字 → 改色。
    单片特征(例如 1 脚标记)不动。
    """
    faces = shape.Faces
    n = len(faces)
    if len(colors) != n or n == 0:
        return colors, 0

    area_by_col = {}
    for i, f in enumerate(faces):
        c = tuple(round(x, 3) for x in colors[i][:3])
        area_by_col[c] = area_by_col.get(c, 0.0) + f.Area
    body = max(area_by_col.items(), key=lambda kv: kv[1])[0]

    bb = shape.BoundBox
    slab = bb.ZMax
    hits = []
    while True:
        cand = []
        for i, f in enumerate(faces):
            fb = f.BoundBox
            col = colors[i]
            if tuple(round(x, 3) for x in col[:3]) == body:
                continue
            if min(col[0], col[1], col[2]) < 0.6:
                continue
            if (fb.ZMin >= slab - 0.03 and fb.ZMax <= slab + 0.0015
                    and fb.ZMin < slab - 1e-4):
                cand.append(i)
        # XY 分块: 相邻(间隙<=0.03mm)的并成一块
        boxes = []
        for i in cand:
            fb = faces[i].BoundBox
            boxes.append([fb.XMin - 0.015, fb.XMax + 0.015,
                          fb.YMin - 0.015, fb.YMax + 0.015, [i]])
        merged = True
        while merged:
            merged = False
            for a in range(len(boxes)):
                for b in range(a + 1, len(boxes)):
                    A, B = boxes[a], boxes[b]
                    if (A[0] <= B[1] and B[0] <= A[1]
                            and A[2] <= B[3] and B[2] <= A[3]):
                        A[0], A[1] = min(A[0], B[0]), max(A[1], B[1])
                        A[2], A[3] = min(A[2], B[2]), max(A[3], B[3])
                        A[4].extend(B[4])
                        boxes.pop(b)
                        merged = True
                        break
                if merged:
                    break
        if len(boxes) < 4:          # 单片特征(如 1 脚标记)不动
            break
        for bx in boxes:
            hits.extend(bx[4])
        break

    if not hits:
        return colors, 0
    new_cols = list(colors)
    bc = (body[0], body[1], body[2], 1.0)
    for i in hits:
        new_cols[i] = bc
    print("[INFO] 抹掉本体刻字 %d 面 (本体色 %.2f,%.2f,%.2f)"
          % (len(hits), body[0], body[1], body[2]))
    return new_cols, len(hits)


def dedupe(cands):
    """cands: list of (vol, obj, colors). Return list of unique-geometry candidates."""
    seen = set()
    uniq = []
    for v, o, colors in sorted(cands, key=lambda t: -t[0]):
        bb = o.Shape.BoundBox
        sig = (round(v, 2), round(bb.XLength, 2),
               round(bb.YLength, 2), round(bb.ZLength, 2))
        if sig in seen:
            print("[INFO] 跳过重复几何副本: %s" % o.Label)
            continue
        seen.add(sig)
        uniq.append((v, o, colors))
    return uniq


# ---------------------------------------------------------------------------
# 带颜色提取 (首选)
# ---------------------------------------------------------------------------
def extract_with_color():
    import FreeCADGui
    FreeCADGui.showMainWindow()          # 需要 ViewObject（offscreen 下不可见）
    try:
        FreeCADGui.getMainWindow().hide()
    except Exception as e:               # 窗口隐藏失败不影响功能
        print("[WARN] hide main window: %s" % e)
    import ImportGui

    doc = FreeCAD.newDocument("jlc_color")
    items = Import.open(src)             # [(Part::Feature, [per-face colors]), ...]
    if not items:
        return False

    cands = []
    for feat, colors in items:
        v = obj_volume(feat)
        if v < 0.5:                      # 太小当碎屑/丝印薄片丢弃
            continue
        if any(k in feat.Label.lower() for k in EXCLUDE):
            continue
        cands.append((v, feat, colors))
    if not cands:
        print("[ERR] 未识别到器件对象(都被当 PCB/文字排除了?)")
        return False

    uniq = dedupe(cands)
    if len(uniq) > 1:
        print("[INFO] 识别出 %d 个不同器件，自动取最大者: %s"
              % (len(uniq), uniq[0][1].Label))
    v, feat, colors = uniq[0]

    # 去掉嘉立创 EDA 的 LCEDA/EasyEDA 水印 logo (独立零体积白色贴片)
    shape, colors, n_logo = strip_logo_decals(feat.Shape.copy(), list(colors))
    # 抹掉刻在本体表面的型号字(SOIC16 之类)
    colors, n_text = strip_engraved_text(shape, colors)

    # 居中 (只平移，面顺序不变 → 颜色仍一一对应)
    bb = shape.BoundBox
    shape.translate(FreeCAD.Vector(
        -(bb.XMin + bb.XMax) / 2.0,
        -(bb.YMin + bb.YMax) / 2.0,
        -bb.ZMin,
    ))

    out_doc = FreeCAD.newDocument("jlc_out")
    f2 = out_doc.addObject("Part::Feature", "Package")
    f2.Shape = shape
    out_doc.recompute()

    n_faces = len(shape.Faces)
    if len(colors) == n_faces:
        f2.ViewObject.DiffuseColor = list(colors)
        colored = True
    else:
        print("[WARN] 面数/颜色数不一致 (%d vs %d)，本次不设色"
              % (n_faces, len(colors)))
        colored = False

    ImportGui.export([f2], out)
    if not os.path.exists(out) or os.path.getsize(out) == 0:
        return False

    bb2 = shape.BoundBox
    print("[OK] %s | %d faces | colors=%s | logo_stripped=%d | %.3f x %.3f x %.3f | vol %.4f mm^3"
          % (feat.Label, n_faces, "yes" if colored else "no", n_logo,
             bb2.XLength, bb2.YLength, bb2.ZLength,
             sum(s.Volume for s in shape.Solids)))
    print("[OK] saved -> %s" % out)
    return True


# ---------------------------------------------------------------------------
# 无颜色兜底 (老逻辑: FreeCAD 无头导出，颜色会丢)
# ---------------------------------------------------------------------------
def extract_plain():
    doc = FreeCAD.newDocument("jlc")
    Import.insert(src, doc.Name)

    cands = []
    for o in doc.Objects:
        v = obj_volume(o)
        if v < 0.5:
            continue
        if any(k in o.Label.lower() for k in EXCLUDE):
            continue
        cands.append((v, o, None))
    if not cands:
        print("[ERR] 未识别到器件对象(都被当 PCB/文字排除了?)")
        return False

    uniq = dedupe(cands)
    tgt = uniq[0][1]
    solids = [s for s in tgt.Shape.Solids if s.Volume > 0.001]
    if not solids:
        print("[ERR] 目标 %s 没有有体积的 solid" % tgt.Label)
        return False

    comp = Part.Compound(solids)
    bb = comp.BoundBox
    comp.translate(FreeCAD.Vector(
        -(bb.XMin + bb.XMax) / 2.0,
        -(bb.YMin + bb.YMax) / 2.0,
        -bb.ZMin,
    ))
    bb2 = comp.BoundBox
    comp.exportStep(out)
    print("[OK] %s | %d solids | %.3f x %.3f x %.3f | vol %.4f mm^3"
          % (tgt.Label, len(solids), bb2.XLength, bb2.YLength, bb2.ZLength,
             sum(s.Volume for s in comp.Solids)))
    print("[OK] saved -> %s" % out)
    return True


def main():
    try:
        ok = extract_with_color()
    except Exception as e:
        print("[WARN] 带颜色导出失败(%s: %s)，回退无颜色模式"
              % (type(e).__name__, e))
        ok = False
    if not ok:
        try:
            ok = extract_plain()
        except Exception as e:
            print("[ERR] 提取失败: %s: %s" % (type(e).__name__, e))
            return 1
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
