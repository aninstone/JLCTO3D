# JLCTO3D - one-click STEP package extractor
# Engine: FreeCAD (headless). Output: <name>_package.step, original face colors kept.
# Please double-click JLCTO3D.bat or JLCTO3D.cmd, NOT this .ps1 file.
param(
    [switch]$FromBat,
    [string]$DroppedFile = ""
)

Add-Type -AssemblyName System.Windows.Forms

if (-not $FromBat) {
    [void][System.Windows.Forms.MessageBox]::Show(
        "Please double-click JLCTO3D.bat or JLCTO3D.cmd to run this tool.`nDo not open .ps1 directly.",
        "JLCTO3D")
    exit
}

# ---------------------------------------------------------------------------
# 1) Locate the extractor script (always relative to this launcher)
# ---------------------------------------------------------------------------
$SCRIPT = Join-Path $PSScriptRoot "scripts\jlc_extract.py"
if (-not (Test-Path $SCRIPT)) {
    [System.Windows.Forms.MessageBox]::Show(
        "Cannot find scripts\jlc_extract.py next to this launcher.`nExpected at:`n$SCRIPT",
        "JLCTO3D Error") | Out-Null
    exit
}

# ---------------------------------------------------------------------------
# 2) Locate FreeCAD's python.exe
#    - env var FREECAD_PYTHON wins if set
#    - otherwise scan common install roots for a FreeCAD* folder
# ---------------------------------------------------------------------------
function Find-FreeCADPython {
    if ($env:FREECAD_PYTHON -and (Test-Path $env:FREECAD_PYTHON)) {
        return $env:FREECAD_PYTHON
    }
    $roots = @(
        $env:ProgramFiles,
        ${env:ProgramFiles(x86)},
        "C:\Program Files",
        "D:\Program Files",
        "E:\Program Files",
        "C:\",
        "D:\"
    )
    foreach ($r in $roots) {
        if (-not $r) { continue }
        if (-not (Test-Path $r)) { continue }
        $hit = Get-ChildItem -Path $r -Filter "FreeCAD*" -Directory -ErrorAction SilentlyContinue |
               Sort-Object Name -Descending |
               ForEach-Object { Join-Path $_.FullName "bin\python.exe" } |
               Where-Object { Test-Path $_ } |
               Select-Object -First 1
        if ($hit) { return $hit }
    }
    return ""
}

$FC = Find-FreeCADPython
if (-not $FC) {
    [System.Windows.Forms.MessageBox]::Show(
        "FreeCAD not found.`n`nInstall FreeCAD 1.x, or set the environment variable FREECAD_PYTHON`nto its python.exe, e.g.`nD:\Program Files\FreeCAD 1.1\bin\python.exe",
        "JLCTO3D Error") | Out-Null
    exit
}

# ---------------------------------------------------------------------------
# 3) Get source STEP: dropped file if valid, otherwise a file dialog
# ---------------------------------------------------------------------------
$src = ""
if ($DroppedFile -and (Test-Path $DroppedFile)) {
    $src = $DroppedFile
}
if (-not $src) {
    $dlg = New-Object System.Windows.Forms.OpenFileDialog
    $dlg.Filter = "STEP files (*.step;*.stp)|*.step;*.stp|All files (*.*)|*.*"
    $dlg.Title = "Select a JLC EDA exported 3D STEP (with PCB)"
    if ($dlg.ShowDialog() -ne 'OK') { exit }
    $src = $dlg.FileName
}

# ---------------------------------------------------------------------------
# 4) Output path: same folder, <original name>_package.step
# ---------------------------------------------------------------------------
$dir  = Split-Path $src
$base = [System.IO.Path]::GetFileNameWithoutExtension($src)
$out  = Join-Path $dir ($base + "_package.step")

# ---------------------------------------------------------------------------
# 5) Run the FreeCAD headless extractor
# ---------------------------------------------------------------------------
Start-Process -FilePath $FC `
    -ArgumentList "`"$SCRIPT`" `"$src`" `"$out`"" `
    -Wait -WindowStyle Hidden | Out-Null

# ---------------------------------------------------------------------------
# 6) Result popup
# ---------------------------------------------------------------------------
if (Test-Path $out) {
    [System.Windows.Forms.MessageBox]::Show(
        "Done! Clean package saved to:`n`n$out",
        "JLCTO3D Success") | Out-Null
} else {
    [System.Windows.Forms.MessageBox]::Show(
        "Failed. Please check:`n- The source is a JLC EDA exported STEP containing a PCB`n- FreeCAD is installed ($FC)`n`nTry running the script manually to see the error:",
        "JLCTO3D Failed") | Out-Null
}
