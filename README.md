# JLCTO3D

**从「嘉立创 EDA (LCEDA / EasyEDA) 导出的含 PCB 的 3D STEP」里，自动抠出干净的单器件封装。**

导出 3D 时嘉立创会把**整块拼板 PCB + 器件**一起给你，这个工具把 PCB 板、丝印字母薄片、重复幽灵副本、以及嘉立创自己打的水印 logo 全部剔掉，只留下器件本体，**并保留原有的面颜色**（黑本体 / 蓝壳 / 镀金引脚 / 白色 1 脚标记等）。

- 一键双击就能用（文件选择框 + 结果弹窗）
- 自动识别器件，**不需要手动指定 label 前缀**
- 输出 `.step`，不依赖 SolidWorks
- 单器件约 5~15 秒

---

## 环境要求

| 依赖 | 说明 |
|---|---|
| [FreeCAD 1.x](https://www.freecad.org/downloads.php) | 必需，用它的 `python.exe` 当引擎（自带 OCCT / PySide） |
| Windows | 启动器是 `.bat` / `.cmd` / `.ps1`；核心脚本跨平台 |
| Python 3.8+ | 用 FreeCAD 自带的即可，无需额外装包 |

FreeCAD 路径是**自动探测**的（扫 `C:\Program Files`、`D:\Program Files`、`Program Files (x86)`、盘符根目录下的 `FreeCAD*` 文件夹）。
如果装在奇怪的位置，设一个环境变量即可：

```cmd
setx FREECAD_PYTHON "D:\Program Files\FreeCAD 1.1\bin\python.exe"
```

---

## 使用方式

### A. 一键启动器（推荐）

**双击 `JLCTO3D.bat`（或 `JLCTO3D.cmd`）** → 弹出文件选择框 → 选那个含 PCB 的 `.step` → 结束会弹窗告诉你结果。

输出文件就在源文件旁边：`<原文件名>_package.step`。

> 不要直接双击 `JLCTO3D.ps1` —— Windows 默认不把 `.ps1` 关联到 PowerShell，会弹「选择打开方式」。这个文件由 `.bat` / `.cmd` 调用。
>
> 也支持拖放：把 `.step` 拖到 `JLCTO3D.bat` 上即可。文件名含空格/括号/中文都安全。

### B. 命令行

```cmd
"D:\Program Files\FreeCAD 1.1\bin\python.exe" scripts\jlc_extract.py <源.step> <输出.step>
```

> ⚠️ 必须用 **FreeCAD 自带的 python.exe**，不要用系统 Python：脚本要 `import FreeCAD / Import / ImportGui / Part`。

### C. 作为 WorkBuddy / Claude Code Skill

整个文件夹就是一个 skill。放进 `~/.workbuddy/skills/JLCTO3D/` 后，在对话里把 `.step` 发过去说「用 JLCTO3D 提取」即可；`SKILL.md` 里有给模型看的完整调用说明与实现细节。

---

## 原理

### 1. 识别器件（不用前缀）
`Import.open()` 读出的对象里，按「有效体积 ≥ 0.5 mm³」+ label 不含 `board / pcb / easyeda / silk / text / ...` 过滤掉 PCB 与丝印；
再用「体积 + 包围盒」做签名去重，丢掉同一器件的幽灵副本；最后取最大的那个。

### 2. 去嘉立创水印（`LCEDA` / `EasyEDA`）
嘉立创的标记分两种，处理方式不同：

| 类型 | 形态 | 处理 |
|---|---|---|
| 贴片 logo（被拆成独立小块贴在壳上） | 典型 **13 个零体积平面小片**（SOIC-16 / SOT-23-8） | 判据「Z 向厚度 ≤ 0.02mm + 体积 ≤ 0.02mm³ + 该 solid 全部面都很亮 + 命中 ≥ 2 片」→ 直接从 `Solids` 里删掉 |
| 贴/刻在最外表面上的 logo 与型号字 | 两种形态：① 几百个 1µm 级碎面刻在顶面（R2512 的 `LCEDA/EasyEDA` = 218 片 + 一块 0.08mm² 的云图标）；② 刻进本体的凹槽（SOIC-16 的 `SOIC16`，深 0.01mm），都删不掉 | 把这些面的**颜色改成该层主色**，标记即隐形（几何仍在，渲染/打印无影响）|

第二种的判据（顶面/底面各自独立判断）：

- 面整体落在最外表面 30µm 薄层内（`ZLength ≤ 0.03`，侧面大面自动排除）；
- 颜色 ≠ **该层主色**（主色 = 最外 **2µm** 内面积最大的颜色，**不是全模型主色**）；
- 单面面积 ≤ 0.05mm² 才算「文字碎面」，同色碎面 ≥ 5 片且在 XY 上 ≥ 3 个独立块；
- 碎面总面积 < 25% 该层主色面积；
- 命中后**就近扩张**：0.6mm 内同色的大块（云图标是一整块 0.08mm² 的面）一并改色，扩张后总面积 >40% 则撤销。

这些条件让**单色孤块的白色 1 脚标记（DFN-6 顶上 2 片）被保留**。

> **踩坑**：早先版本用「全部面里总面积最大的颜色」当本体主色 —— R2512 因此翻车：内部一块**看不见的实心块**有 46.5mm² 白面，把白色顶成主色，于是所有白色水印面都被跳过。必须在**最外 2µm 薄层内**统计主色。

### 3. 带颜色导出（关键坑）
- 无头模式下 `Import.export()` / `Part.export()` **根本不写颜色**，即使设了 `ShapeColor` / `ShapeMaterial`。
- 颜色数据只在 `Import.open()` 的返回值里：`[(Part::Feature, [逐面颜色...]), ...]`。
- 想把颜色写进 STEP 必须用 `ImportGui.export()`，而 `ImportGui` 需要 ViewObject 存在。
- 取巧办法：`FreeCADGui.showMainWindow()` 一下 ViewObject 就有了（普通情况下会闪窗口），
  配合环境变量 `QT_QPA_PLATFORM=offscreen` + `getMainWindow().hide()` → **离屏运行，屏幕上什么都不闪**。
- 居中只做平移、不动面顺序，所以颜色列表可以 1:1 灌回 `ViewObject.DiffuseColor`。

若带色流程出任何异常，脚本会**自动回退到无颜色纯净 STEP**，保证仍然出结果。

---

## 文件说明

```
JLCTO3D.bat / JLCTO3D.cmd   一键启动器（双击）
JLCTO3D.ps1                 启动器实现（文件框 + 弹窗 + FreeCAD 自动探测），不要直接双击
SKILL.md                    给 AI Agent 看的 skill 说明
scripts/jlc_extract.py      核心引擎：识别 + 去水印 + 带色导出
scripts/preview.py          自检工具：把 STEP 按面颜色渲染成 PNG（画家算法），肉眼确认水印清没清干净
scripts/strip_pcb.py        纯 Python 去板实验版（不依赖 FreeCAD，秒级，无颜色）
```

`preview.py` 用法：

```cmd
python.exe scripts\preview.py <源.step> <out.png> [top|iso] [宽] [高] [r,g,b]
```

最后一个参数可选：只画该颜色的面（画成深色），用来单独看某个特征的形状。

> `strip_pcb.py` 只对「板是单一实体」的简单导出可靠；嘉立创的板是「基板平铺拼整板」，
> 删除后会出现悬空引用 / 误删，所以默认走 FreeCAD 引擎（可靠但也慢一点）。

---

## 已知限制

- 立创的单体 3D 模型放在华为私有 OBS 上，纯 `curl` 直下不到；EDA 编辑器又是 WebGL，无头浏览器点不动。
  所以「在 EDA 里放置器件 → 导出 3D」这一步需要手动点两下，本工具负责导出之后的「抠单器件」。
- 带色 STEP 因为逐面颜色，文件会偏大（单器件约 1~10MB），属正常。
- `FCQFN-25` 这类本来就是单色灰模型、没有 logo 也没有刻字的封装，流程会「无命中」，属正常。
- 判断「外壳顶/底」**不能**用 `shape.BoundBox.ZMax`：引脚会伸出去导致 bbox 比本体大
  （SOIC 的引脚伸到 -0.074，logo 贴到 2.801），脚本里用的是固定薄层阈值。

---

## License

MIT
