---
name: 嘉立创封装3D
agent_created: true
summary: 给一个「含 PCB 的嘉立创 EDA 导出 STEP」，自动识别并提取干净单器件封装，输出 .step。前半段「去嘉立创找器件」用 lceda-package-fetch skill 定位，本 skill 负责后半段「抠单器件」。
description: >
  用户从嘉立创 EDA 导出含 PCB 的 3D STEP 后，把文件甩给本 skill，自动：
  用 FreeCAD 识别器件对象(无需手动给 label 前缀)，剔除 PCB 板/丝印字母薄片，
  去除同一器件的幽灵副本，去掉嘉立创自己打在外壳上的 LCEDA/EasyEDA 水印 logo
  与刻在本体上的型号字，居中后导出干净封装 STEP(.step)。
  默认保留原 STEP 的面颜色(黑本体/蓝壳/镀金引脚等)，不调用 SolidWorks，
  约 5~15 秒完成，启动器带文件选择框+结果弹窗、离屏运行不闪窗口。
---

# JLCTO3D — 嘉立创导出 STEP → 干净单器件封装 (.step)

## 何时用
- 用户给一个 `.step`(来自嘉立创 EDA 导出 3D，文件里包含 PCB 板)，要其中的单个器件封装。
- 这是「嘉立创封装获取」完整流程的后半段：前半段(搜器件+在 EDA 放置导出)用 `lceda-package-fetch` skill 定位，导出后交给本 skill 抠。

## 设计决定(用户明确)
- **不打开 SolidWorks**：只导出 .step，不生成 .SLDPRT(用户要求"不用打开solidworks了 直接导出成step就行了")。
- **保留原始颜色**：导出时保留原 STEP 的面颜色(黑本体/蓝壳/镀金引脚等)，不再是一律白色。
- **不留嘉立创水印**：外壳上的 `LCEDA / EasyEDA` logo(含云图标)和本体的型号刻字一律去掉(用户要求"颜色对了 但是上面的 LCEDA丝印没去掉")。
- **不闪退/不闪窗**：启动器用 PowerShell 文件选择框 + 结果消息框；FreeCAD 用 `QT_QPA_PLATFORM=offscreen` 离屏跑，屏幕上不会弹窗也不会闪。
- **前缀不重要**：FreeCAD 自动识别最大器件、跳过幽灵副本，永不因 label 前缀(U1~/U2~)报错。
- **快**：单命令调用 FreeCAD 引擎，约 5~15 秒出干净、带色的封装。

## 调用方式

### A. 对话里(最省事)
把含 PCB 的 `.step` 发我，说「用 JLCTO3D skill 提取」，我直接加载 `jlc_extract.py` 跑，秒级出结果。

### B. 完全自助(双击即可, 不闪退)
**双击 `D:\Downloads\器件3D\JLCTO3D.bat` 或 `JLCTO3D.cmd`** → 弹出文件选择框 → 选含 PCB 的 `.step` → 自动出 `<原名>_package.step`，结束弹窗提示成功/失败。

> ⚠️ **不要直接双击 `JLCTO3D.ps1`**：Windows 默认不认识 `.ps1` 文件，会弹出「选择应用打开 .ps1」。若误点，ps1 自身也会弹窗提示你双击 `.bat`/`.cmd`。
>
> 也支持拖放：简单文件名拖放能用；复杂文件名会自动转成弹框选文件，不会崩。

### C. 直接跑脚本
```
:: 提取(必须 FreeCAD 的 python.exe, 自动识别无需前缀, 自动保留颜色)
"D:\Program Files\FreeCAD 1.1\bin\python.exe" <skill>/scripts/jlc_extract.py <源.step> <输出.step>
```

## 脚本清单(自包含)
- `scripts/jlc_extract.py` — FreeCAD 自动识别 + 提取 + **保留颜色** + **去水印**(核心引擎)。
  内部流程：`Import.open()` 读对象及其逐面颜色 → 去嘉立创水印(见下) → 平移居中 → `ImportGui.export()` 带色写出。
  若带色流程异常，会自动回退到「无颜色纯净 STEP」，保证仍能出结果。
- `JLCTO3D.bat` / `JLCTO3D.cmd` + `JLCTO3D.ps1` — 一键启动器(文件框+弹窗, 无 SW)。`.bat`/`.cmd` 任意双击；`.ps1` 不要直接双击。
- `scripts/preview.py` — 可选自检工具：把 STEP 顶视图渲染成 PNG(按面颜色，画家算法)，用来肉眼确认 logo/刻字是否干净。
  用法：`python.exe preview.py <源.step> <out.png> [top|iso] [宽] [高]`。同一文件只画一种颜色时可加第 7 参 `r,g,b`(此时画深色)。
- `scripts/strip_pcb.py` — 纯 Python 去板实验版(不依赖 FreeCAD，秒级，无颜色)。
  ⚠️ 仅对「板为单一实体」的简单导出可靠；嘉立创拼板(板基板平铺)会出现悬空引用/误删，故默认走 FreeCAD 引擎。

## 去嘉立创水印 (LCEDA / EasyEDA) 的实现
嘉立创导出的器件模型上会带两种自己的标记，必须去掉。**按面「本地判定」，不要用全模型主色**：

1. **贴片式 logo**（被拆成独立「零体积平面小片」贴在外壳上，SOIC-16 / SOT-23-8 各 13 片）
   - 判据：`Z 向厚度<=0.02mm` 且 `体积<=0.02mm³` 且 `该 solid 全部面都很亮(每通道>=0.8)`，且命中片数 `>=2`。
   - 处理：直接从 `shape.Solids` 里剔除，按 solid 顺序重建 `Part.makeCompound` + 颜色列表（compound 的 `Faces` 是按 solid 顺序排列的，颜色可 1:1 对应）。

2. **贴/刻在最外表面上的 logo 与型号字**（`strip_surface_marks`，主力逻辑）
   - 可能是几百个 1µm 级碎面刻在顶面（R2512 的 `LCEDA/EasyEDA`：218 片 + 一块 0.08mm² 的云图标），
     也可能是刻进本体的凹槽（SOIC-16 的 `SOIC16`，深 0.01mm）——删不掉也不能布尔补面。
   - 但它们可见只是因为被上了与所在表面不同的颜色 → **把这批面的颜色改成该层主色**即隐形（几何仍在，渲染/打印无影响）。
   - 判据（顶面/底面各自独立判断）：
     * 面整体落在最外表面 30µm 薄层内（`ZLength<=0.03`，侧面大面自动排除）
     * 颜色 != 该层主色（**主色 = 最外 2µm 内面积最大的颜色**，不是全模型主色！）
     * 单面面积 `<=0.05mm²` 才算「文字碎面」，同色碎面 `>=5` 片且在 XY 上 `>=3` 个独立块
     * 碎面总面积 `< 25%` 该层主色面积
   - 命中后「就近扩张」：把距这些碎面 0.6mm 内、同色的大块（云图标是一整块 0.08mm² 的面）一并改色；
     扩张后总面积 `>40%` 主色面积则撤销（判为误判）。
   - 保护的 1 脚标记：单色孤块（DFN-6 顶上 2 片 0.0118mm²、SOT-23-8 的灰圆块）< 5 片，永远不命中。

### ⚠️ 血泪坑：全模型主色会选错
之前用「器件所有面里总面积最大的颜色」当本体色 → R2512 翻车：内部那块**看不见的实心块**有 46.5mm² 白面，
把白色顶成「主色」，于是「把白面改成本体色」这条逻辑把所有白色面（= 水印）全部跳过 → `mark_faces=0`，丝印原样保留。
**正解：只在最外 2µm 薄层内统计面积取主色**，内部隐藏面（且往往是贯穿面，`ZLength>0.03`）天然被排除。

另外「文字碎面」不能用「XY 分块数」一刀切：R2512 的云图标只占 1 块、面积却比文字笔画大 100 倍，
既过不了 `>=3 块`、又超过 `<=0.05mm²`。所以要先靠碎面群锁定「这里就是水印」，再就近把同色大块吸进来。

## 颜色实现要点(踩坑记录)
- 无头 `Import.export()` / `Part.export()` **不写颜色**(即使设了 ShapeColor)。
- `Import.open()` 会返回 `[(Part::Feature, [逐面颜色...]), ...]`，颜色数据在这。
- 写 STEP 带色必须 `ImportGui.export()`；而 `ImportGui` 需要 ViewObject 存在。
- 只要 `FreeCADGui.showMainWindow()` 一下，ViewObject 就出现，但普通窗口会闪；
  用 `QT_QPA_PLATFORM=offscreen` 环境变量 + `getMainWindow().hide()` 即可隐形。
- 平移居中不改变面顺序，因此颜色列表可原样灌回 `ViewObject.DiffuseColor`。
- 判断面的 Z 位置别用 `shape.BoundBox.ZMax/ZMin` 当「外壳顶/底」：引脚会伸出去，
  使 bbox 比本体大(SOIC 引脚到 -0.074、logo 贴片到 2.801)。要用「本体主色面的 Z」或固定薄层阈值。

## 已知限制
- 立创单体 3D 在华为私有 OBS，纯 curl 直下不到；EDA 又是 WebGL 无头点不动 → 「放板导出」这步需用户手动在 EDA 点 2 下。本 skill 专治导出后的「抠单器件」。
- 会话 cookie 失效搜索报 403 时，用 `lceda-package-fetch` 的刷新流程重登立创 EDA 取新 cookie。
- 带色 STEP 因逐面颜色会略大(单器件约 1~10MB)，属正常；若只在意几何可无视。
- 白色 **1 脚标记**(DFN-6 / SOT-23-8 顶上那点/小圆点)是本体自带特征，按设计**保留**，不要误删。
  验证方法：输出文件里「顶面 30µm 内、亮色、面积<=0.05mm²」的面数，DFN-6 应为 2（0.0118mm²），R2512 / SOIC-16 / SOT-23-8 应为 0。
- FCQFN-25 这类本来就是单色灰模型、无 logo 无刻字的封装，流程会「无命中」，属正常。
