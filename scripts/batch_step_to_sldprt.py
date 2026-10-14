# -*- coding: utf-8 -*-
"""Batch convert STEP file(s) to same-name .SLDPRT (SolidWorks native, previewable)
next to them, via SolidWorks COM. Imported STEP colors are preserved by SolidWorks.

Usage: batch_step_to_sldprt.py <file.step | folder>
Best effort: skips files that already have a .SLDPRT.
Self-contained: only needs python + pywin32 + SolidWorks.
"""
import glob
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pythoncom  # noqa: E402
from win32com.client import VARIANT, Dispatch  # noqa: E402


def call(obj, name, *args):
    m = getattr(obj, name)
    return m(*args) if callable(m) else m


def empty_dispatch():
    return VARIANT(pythoncom.VT_DISPATCH, None)


def convert_one(sw, src, dst, i, n, t0):
    if os.path.exists(dst) and os.path.getsize(dst) > 5000:
        print("[%d/%d] %s skip (exists)" % (i, n, os.path.basename(dst)), flush=True)
        return True
    errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    model = None
    try:
        model = sw.GetOpenDocumentByName(src)
    except Exception:
        model = None
    if model is None:
        try:
            import_data = sw.GetImportFileData(src)
        except Exception:
            import_data = None
        if import_data is None:
            import_data = empty_dispatch()
        try:
            model = sw.LoadFile4(src, "r", import_data, errors)
        except Exception as e:
            print("[%d/%d] %s OPEN-EXC %s" % (i, n, os.path.basename(src), repr(e)[:80]), flush=True)
            return False
    if model is None:
        print("[%d/%d] %s OPEN-FAIL err=%s" % (i, n, os.path.basename(src), errors.value), flush=True)
        return False
    title = call(model, "GetTitle")
    try:
        ok = model.Extension.SaveAs(dst, 0, 1, empty_dispatch(), errors, warnings)
    except Exception as e:
        ok = False
        print("   SAVE-EXC %s" % repr(e)[:80], flush=True)
    try:
        sw.CloseDoc(title)
    except Exception:
        pass
    if ok and os.path.exists(dst) and os.path.getsize(dst) > 5000:
        print("[%d/%d] %s ok %dKB (%.0fs)"
              % (i, n, os.path.basename(dst), os.path.getsize(dst) // 1024, time.time() - t0), flush=True)
        return True
    print("[%d/%d] %s SAVE-FAIL err=%s" % (i, n, os.path.basename(dst), errors.value), flush=True)
    return False


def main():
    if len(sys.argv) < 2:
        print("usage: batch_step_to_sldprt.py <file.step | folder>")
        return 1
    target = os.path.abspath(sys.argv[1])
    if os.path.isdir(target):
        steps = sorted(glob.glob(os.path.join(target, "*.step")))
    else:
        steps = [target]
    steps = [s for s in steps if os.path.exists(s)]
    if not steps:
        print("no STEP files found at:", target)
        return 1

    t0 = time.time()
    try:
        sw = Dispatch("SldWorks.Application")
    except Exception as e:
        print("SolidWorks COM connect failed: %s" % repr(e)[:120])
        return 1

    ok_n = fail_n = 0
    for i, src in enumerate(steps, 1):
        dst = os.path.splitext(src)[0] + ".SLDPRT"
        if convert_one(sw, src, dst, i, len(steps), t0):
            ok_n += 1
        else:
            fail_n += 1
    print("DONE ok=%d fail=%d elapsed=%.0fs" % (ok_n, fail_n, time.time() - t0), flush=True)
    return 0 if (ok_n > 0 and fail_n == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
