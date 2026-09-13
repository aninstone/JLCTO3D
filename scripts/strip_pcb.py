# -*- coding: utf-8 -*-
"""
JLCTO3D - 纯 Python 去除 STEP 中的 PCB / 丝印 / 铜皮, 导出干净单体封装。
不依赖 FreeCAD / SolidWorks, 秒级完成。

判定规则:
  - 含 PCB 的导出里, 真正的器件在一个名字像封装(如 PG-TSON-8_L5.0-W6.0...)
    的 ADVANCED_BREP_SHAPE_REPRESENTATION 中; 板/铜皮/丝印的表示通常无名(空)
    或名字含 board/copper/silk/stiffener/fpc。
  - 保留"有封装名"的表示, 删除其余; 共享几何上下文会被保护不误删。

用法:
  strip_pcb.py <源.step> [输出.step]
"""
import re, sys, os

BOARD_NAME_RE = re.compile(r'board|pcb|easyeda|copper|silk|stiffener|flex|fpc', re.I)
REP_TYPES = ('ADVANCED_BREP_SHAPE_REPRESENTATION', 'SHAPE_REPRESENTATION', 'BREP_SHAPE_REPRESENTATION')
SOLID_TYPES = ('MANIFOLD_SOLID_BREP', 'FACETED_BREP', 'BREP_SOLID')

def parse_step(path):
    txt = open(path, encoding='utf-8', errors='replace').read()
    m = re.search(r'DATA;', txt)
    start = m.end()
    end = txt.index('ENDSEC;', start)
    data = txt[start:end]
    entities = {}
    pat = re.compile(r'#(\d+)\s*=\s*([A-Z][A-Z0-9_]*)\s*\(')
    i = 0; L = len(data)
    while True:
        mm = pat.search(data, i)
        if not mm:
            break
        idn = int(mm.group(1)); typ = mm.group(2)
        p = mm.end(); depth = 1; j = p
        while j < L and depth > 0:
            c = data[j]
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
            j += 1
        entities[idn] = (typ, data[mm.start():j])
        i = j
    return txt, start, end, entities

def build_refs(entities):
    fwd = {k: set() for k in entities}
    rev = {k: set() for k in entities}
    for k, (typ, full) in entities.items():
        for m in re.finditer(r'#(\d+)', full):
            t = int(m.group(1))
            if t in entities:
                fwd[k].add(t); rev[t].add(k)
    return fwd, rev

def closure(fwd, rev, seeds):
    # 仅正向闭包: 从表示向下收集其几何, 避免共享上下文把板几何误并入保留集
    seen = set(); stack = [s for s in seeds if s in fwd]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        for x in fwd.get(n, ()):
            if x not in seen:
                stack.append(x)
    return seen

def rep_name(full):
    m = re.search(r"\(\s*'([^']*)'", full)
    return m.group(1) if m else ''

def main():
    if len(sys.argv) < 2:
        print("用法: strip_pcb.py <源.step> [输出.step]")
        sys.exit(1)
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else (
        os.path.join(os.path.dirname(src),
                     os.path.splitext(os.path.basename(src))[0] + "_package.step"))
    txt, start, end, entities = parse_step(src)
    fwd, rev = build_refs(entities)

    reps = [k for k, (t, _) in entities.items() if t in REP_TYPES]
    keep_reps = []
    remove_reps = []
    for r in reps:
        nm = rep_name(entities[r][1])
        if BOARD_NAME_RE.search(nm) or nm == '':
            remove_reps.append(r)
        else:
            keep_reps.append(r)
    print("[INFO] 表示总数 %d, 保留(器件)%d, 删除(板/层)%d"
          % (len(reps), len(keep_reps), len(remove_reps)))
    for r in keep_reps:
        print("  保留: #%d  %s" % (r, rep_name(entities[r][1])[:60]))
    for r in remove_reps:
        print("  删除: #%d  %s" % (r, rep_name(entities[r][1])[:40] or "(空名)"))

    # 收集保留/删除的实体(solid)与表示自身
    keep_seeds = list(keep_reps)
    remove_seeds = list(remove_reps)
    # 一并把板类 PRODUCT 也列为删除种子
    for k, (t, full) in entities.items():
        if t == 'PRODUCT' and BOARD_NAME_RE.search(full):
            remove_seeds.append(k)

    keep_clo = closure(fwd, rev, keep_seeds)
    remove_clo = closure(fwd, rev, remove_seeds)
    remove_ids = remove_clo - keep_clo

    if not keep_reps:
        print("[ERR] 没识别到任何器件表示, 原文件结构可能不符, 已中止")
        sys.exit(2)

    print("[INFO] 保留实体 %d, 删除实体 %d" % (len(keep_clo), len(remove_ids)))
    lines = txt[start:end].split('\n')
    kept = []; removed = 0
    for ln in lines:
        mm = re.match(r'\s*#(\d+)\s*=', ln)
        if mm and int(mm.group(1)) in remove_ids:
            removed += 1; continue
        kept.append(ln)
    new_txt = txt[:start] + '\n'.join(kept) + txt[end:]
    with open(out, 'w', encoding='utf-8') as fp:
        fp.write(new_txt)
    print("[OK] 已写出: %s  (删除 %d 行)" % (out, removed))

if __name__ == '__main__':
    main()
