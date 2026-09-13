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


def count_blocks(boxes, gap=0.01):
    """把 XY 包围盒按「间隙 <= gap 就相邻」合并，返回独立块数。"""
    bs = [[b[0] - gap, b[1] + gap, b[2] - gap, b[3] + gap] for b in boxes]
    merged = True
    while merged:
        merged = False
        for a in range(len(bs)):
            for b in range(a + 1, len(bs)):
                A, B = bs[a], bs[b]
                if (A[0] <= B[1] and B[0] <= A[1]
                        and A[2] <= B[3] and B[2] <= A[3]):
                    A[0], A[1] = min(A[0], B[0]), max(A[1], B[1])
                    A[2], A[3] = min(A[2], B[2]), max(A[3], B[3])
                    bs.pop(b)
                    merged = True
                    break
            if merged:
                break
    return len(bs)


def strip_surface_marks(shape, colors):
    """抹掉 EasyEDA 打/刻在器件外表面上的水印 logo(LCEDA/EasyEDA)与型号刻字。

    实现思路分两步，互补覆盖两类模型：
    1) 全局聚类：先用大面面积定出「本体主色」(通常是暗灰/黑)，然后把所有
       小面积、高亮度(>=0.7)、颜色不同于本体的碎面按 XY  proximity 聚类。
       聚成 >=5 片、总面积 >=0.01mm² 的簇就是水印/型号字 → 改成本体色。
       这能处理 PDIP/SOIC 等「本体一个 solid、顶面圆润，水印被切成百片小白面」
       的情况（旧版按 Z 薄层找主色会失效）。
    2) 局部薄层：对扁平器件顶面，仍保留原来的「最外 30µm 薄层 + 局部主色」
       逻辑作为兜底，防止 R2512 这类内部有大块隐形容器把全局主色带偏的情况。

    1 脚标记通常只有 1~4 个小块，不会进入 >=5 的簇；金属大面因面积大也不参与。
    命中只改颜色不改几何，因为有的刻字是凹进本体的，删面会破坏 solid。
    """
    faces = shape.Faces
    n = len(faces)
    if len(colors) != n or n == 0:
        return colors, 0

    def ckey(c):
        return tuple(round(x, 3) for x in c[:3])

    bb = shape.BoundBox
    new_cols = list(colors)
    hits_total = 0

    # ------------------------------------------------------------------
    # 1) 全局聚类（处理 PDIP/SOIC 等圆润顶面）
    # ------------------------------------------------------------------
    # 本体主色：面积大、且不太亮（排除金属/水印）的面中占多数的颜色
    body_color = None
    area_by_col = {}
    body_xmin = body_xmax = body_ymin = body_ymax = None
    for i, f in enumerate(faces):
        c = colors[i]
        ck = ckey(c)
        if min(c) >= 0.7:       # 高亮面很可能是金属/水印，不当成本体候选
            continue
        if f.Area < 0.005:
            continue
        area_by_col[ck] = area_by_col.get(ck, 0.0) + f.Area
        # 同步用「大且暗」的面估算本体 XY  footprint，排除引脚末端
        if f.Area >= 0.05:
            fb = f.BoundBox
            if body_xmin is None:
                body_xmin, body_xmax = fb.XMin, fb.XMax
                body_ymin, body_ymax = fb.YMin, fb.YMax
            else:
                body_xmin = min(body_xmin, fb.XMin)
                body_xmax = max(body_xmax, fb.XMax)
                body_ymin = min(body_ymin, fb.YMin)
                body_ymax = max(body_ymax, fb.YMax)
    if area_by_col:
        body_color = max(area_by_col.items(), key=lambda kv: kv[1])[0]
    else:
        # 兜底：取最大单个面颜色
        i = max(range(n), key=lambda j: faces[j].Area)
        body_color = ckey(colors[i])
    if body_xmin is None:
        body_xmin, body_xmax = bb.XMin, bb.XMax
        body_ymin, body_ymax = bb.YMin, bb.YMax
    else:
        margin = 0.15
        body_xmin -= margin
        body_xmax += margin
        body_ymin -= margin
        body_ymax += margin

    def in_footprint(i):
        fb = faces[i].BoundBox
        cx = (fb.XMin + fb.XMax) * 0.5
        cy = (fb.YMin + fb.YMax) * 0.5
        return (body_xmin <= cx <= body_xmax and body_ymin <= cy <= body_ymax)

    # 候选面：小、亮、颜色不同于本体、Z 向薄、在本体 footprint 内、且靠近顶面。
    # 嘉立创 LCEDA/EasyEDA 水印只打在本体顶面；底面大金属散热焊盘不处理。
    z_top = bb.ZMax - 0.10
    small_cands = []
    for i, f in enumerate(faces):
        c = colors[i]
        if ckey(c) == body_color:
            continue
        if min(c) < 0.7:
            continue
        if f.Area > 0.05:
            continue
        if f.BoundBox.ZLength > 0.05:
            continue
        if f.BoundBox.ZMax < z_top:
            continue
        if not in_footprint(i):
            continue
        small_cands.append(i)

    if len(small_cands) >= 5:
        gap = 0.25  # 同一字母/图标的相邻小面间距一般不超过 0.25mm
        used = set()
        clusters = []
        for i in small_cands:
            if i in used:
                continue
            cluster = [i]
            used.add(i)
            queue = [i]
            while queue:
                cur = queue.pop(0)
                cbb = faces[cur].BoundBox
                for j in small_cands:
                    if j in used:
                        continue
                    jbb = faces[j].BoundBox
                    if (cbb.XMin - gap <= jbb.XMax and jbb.XMin <= cbb.XMax + gap
                            and cbb.YMin - gap <= jbb.YMax
                            and jbb.YMin <= cbb.YMax + gap):
                        used.add(j)
                        cluster.append(j)
                        queue.append(j)
            clusters.append(cluster)

        # 把小簇邻近的「大块亮面」也一起拉进来(如云图标的外轮廓面 0.2mm^2)
        expand_candidates = []
        for i, f in enumerate(faces):
            if i in small_cands:
                continue
            c = colors[i]
            if ckey(c) == body_color:
                continue
            if min(c) < 0.7:
                continue
            if f.Area > 0.5:
                continue
            if f.BoundBox.ZLength > 0.05:
                continue
            if f.BoundBox.ZMax < z_top:
                continue
            if not in_footprint(i):
                continue
            expand_candidates.append(i)

        for cluster in clusters:
            if len(cluster) < 15:            # 1 脚标记通常 <10 面；水印/型号字簇大得多
                continue
            tot = sum(faces[i].Area for i in cluster)
            if tot < 0.01:
                continue
            # 估算簇的 XY 包围盒
            xs = [faces[i].BoundBox.XMin for i in cluster] + \
                 [faces[i].BoundBox.XMax for i in cluster]
            ys = [faces[i].BoundBox.YMin for i in cluster] + \
                 [faces[i].BoundBox.YMax for i in cluster]
            zone = [min(xs) - 0.3, max(xs) + 0.3, min(ys) - 0.3, max(ys) + 0.3]
            for i in expand_candidates:
                if i in cluster:
                    continue
                fb = faces[i].BoundBox
                if (zone[0] <= fb.XMax and fb.XMin <= zone[1]
                        and zone[2] <= fb.YMax and fb.YMin <= zone[3]):
                    cluster.append(i)
                    tot += faces[i].Area

            for i in cluster:
                new_cols[i] = (body_color[0], body_color[1], body_color[2], 1.0)
            hits_total += len(cluster)
            print("[INFO] 全局抹掉水印 %d 面 (颜色 -> 本体 %.2f,%.2f,%.2f, 面积 %.3f mm^2, bbox x%.2f..%.2f y%.2f..%.2f)"
                  % (len(cluster), body_color[0], body_color[1], body_color[2],
                     tot, min(xs), max(xs), min(ys), max(ys)))

    # ------------------------------------------------------------------
    # 2) 局部薄层兜底（处理 R2512 等扁平器件）
    # ------------------------------------------------------------------
    for which in ("top", "bottom"):
        near, win = [], []
        for i, f in enumerate(faces):
            fb = f.BoundBox
            if fb.ZLength > 0.03:            # 侧面/贯穿面不参与
                continue
            d_out = (bb.ZMax - fb.ZMax) if which == "top" else (fb.ZMin - bb.ZMin)
            if d_out < -0.0015:              # 超出参考面(异常)，跳过
                continue
            if d_out <= 0.002:
                near.append(i)
            if d_out <= 0.03:
                win.append(i)
        if not near or not win:
            continue

        # 该层主色 = 最外 2µm 内面积最大的颜色
        area_by_col = {}
        for i in near:
            c = ckey(colors[i])
            area_by_col[c] = area_by_col.get(c, 0.0) + faces[i].Area
        surface = max(area_by_col.items(), key=lambda kv: kv[1])
        surf_color, surf_area = surface[0], surface[1]
        if surf_area <= 0:
            continue

        # 第一轮: 「文字碎面」= 与表层主色不同、且面积很小的表层碎片
        by_col = {}
        for i in win:
            if ckey(colors[i]) == surf_color:
                continue
            if faces[i].Area > 0.05:
                continue
            by_col.setdefault(ckey(colors[i]), []).append(i)

        for c, idx in sorted(by_col.items(), key=lambda kv: -len(kv[1])):
            if len(idx) < 5:                 # 单片特征(如 1 脚标记)不动
                continue
            tot = sum(faces[i].Area for i in idx)
            if tot > 0.25 * surf_area:
                continue
            boxes = []
            for i in idx:
                fb = faces[i].BoundBox
                boxes.append([fb.XMin, fb.XMax, fb.YMin, fb.YMax])
            nb = count_blocks(boxes)
            if nb < 3:                       # 单片/单块特征不动
                continue

            # 第二轮: 紧邻文字的同色大块也一起抹(logo 里的云图标就是一整块 0.08mm^2 的面)
            grow = 0.6
            zones = [[b[0] - grow, b[1] + grow, b[2] - grow, b[3] + grow]
                     for b in boxes]
            idx = list(idx)
            for i in win:
                if i in idx or ckey(colors[i]) != c:
                    continue
                fb = faces[i].BoundBox
                if any(z[0] <= fb.XMax and fb.XMin <= z[1]
                       and z[2] <= fb.YMax and fb.YMin <= z[3] for z in zones):
                    idx.append(i)
                    tot += faces[i].Area
            if tot > 0.4 * surf_area:        # 长出太多 -> 判定失误，放弃
                continue

            for i in idx:
                new_cols[i] = (surf_color[0], surf_color[1], surf_color[2], 1.0)
            hits_total += len(idx)
            print("[INFO] 抹掉%s面水印 %d 面 (颜色 %.2f,%.2f,%.2f -> 主色 %.2f,%.2f,%.2f, %d 块, 面积 %.3f/%.3f mm^2)"
                  % ("顶" if which == "top" else "底", len(idx),
                     c[0], c[1], c[2], surf_color[0], surf_color[1], surf_color[2],
                     nb, tot, surf_area))
    return new_cols, hits_total


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
    # 抹掉贴/刻在本体最外表面上的水印字与型号字(如 SOIC16 / R2512 / PDIP 上的 LCEDA logo)
    colors, n_text = strip_surface_marks(shape, colors)

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
    print("[OK] %s | %d faces | colors=%s | logo_stripped=%d | mark_faces=%d | %.3f x %.3f x %.3f | vol %.4f mm^3"
          % (feat.Label, n_faces, "yes" if colored else "no", n_logo, n_text,
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
