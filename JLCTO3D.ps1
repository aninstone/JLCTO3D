# JLCTO3D - one-click STEP package extractor
# Engine: FreeCAD (headless). Output: <name>_package.step, original face colors kept.
# Please double-click JLCTO3D.bat or JLCTO3D.cmd, NOT this .ps1 file.
param(
    [switch]$FromBat,
    [string]$DroppedFile = "",
    [switch]$NoPopup
)

Add-Type -AssemblyName System.Windows.Forms

function Show-Msg([string]$text, [string]$title) {
    if (-not $NoPopup) {
        [System.Windows.Forms.MessageBox]::Show($text, $title) | Out-Null
    }
}

if (-not $FromBat) {
    Show-Msg "Please double-click JLCTO3D.bat or JLCTO3D.cmd to run this tool.`nDo not open .ps1 directly." "JLCTO3D"
    exit
}

$log = New-Object System.Collections.Generic.List[string]
function Log([string]$s) {
    $log.Add($s)
    Write-Host $s
}

# ---------------------------------------------------------------------------
# 1) Locate the extractor script (always relative to this launcher)
# ---------------------------------------------------------------------------
$SCRIPT = Join-Path $PSScriptRoot "scripts\jlc_extract.py"
if (-not (Test-Path $SCRIPT)) {
    Show-Msg "Cannot find scripts\jlc_extract.py next to this launcher.`nExpected at:`n$SCRIPT" "JLCTO3D Error"
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
    Show-Msg "FreeCAD not found.`n`nInstall FreeCAD 1.x, or set the environment variable FREECAD_PYTHON`nto its python.exe, e.g.`nD:\Program Files\FreeCAD 1.1\bin\python.exe" "JLCTO3D Error"
    exit
}
Log "FreeCAD python: $FC"

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
Log "Source: $src"

# ---------------------------------------------------------------------------
# 4) Output path: same folder, <original name>_package.step
# ---------------------------------------------------------------------------
$dir  = Split-Path $src
$base = [System.IO.Path]::GetFileNameWithoutExtension($src)
$out  = Join-Path $dir ($base + "_package.step")

# ---------------------------------------------------------------------------
# 5) Run the FreeCAD headless extractor
# ---------------------------------------------------------------------------
$startAt = Get-Date
$p = Start-Process -FilePath $FC `
    -ArgumentList "`"$SCRIPT`" `"$src`" `"$out`"" `
    -Wait -WindowStyle Hidden -PassThru
Log "FreeCAD extractor exit code: $($p.ExitCode)"

# ---------------------------------------------------------------------------
# 5.5) Also produce SolidWorks-native .SLDPRT next to each STEP (best effort:
#      silently skipped when python+pywin32 or SolidWorks is unavailable)
# ---------------------------------------------------------------------------
$folder = Join-Path $dir ($base + "_packages")
$conv = Join-Path $PSScriptRoot "scripts\batch_step_to_sldprt.py"
$pyWin = $null
foreach ($cand in @($env:JLCTO3D_SW_PY, "C:/Users/Simon/.workbuddy/binaries/python/versions/3.13.12.old.26408/python.exe", "python", "py")) {
    if (-not $cand) { continue }
    try {
        $null = & $cand -c "import win32com.client" 2>$null
        Log "probe '$cand' -> exit $LASTEXITCODE"
        if ($LASTEXITCODE -eq 0) { $pyWin = $cand; break }
    } catch {
        Log "probe '$cand' -> exception: $($_.Exception.Message)"
        continue
    }
}
if ($pyWin -and (Test-Path $conv)) {
    $swTarget = $null
    # Prefer $out ONLY if this run actually (re)generated it; multi-component
    # exports leave $out stale from an older single-component run.
    if ((Test-Path $out) -and ((Get-Item $out).LastWriteTime -ge $startAt)) {
        $swTarget = $out
    } elseif (Test-Path $folder) {
        $swTarget = $folder
    } elseif (Test-Path $out) {
        $swTarget = $out
    }
    Log "SLDPRT target: $swTarget"
    if ($swTarget) {
        try {
            $outLine = & $pyWin $conv $swTarget 2>&1
            Log ($outLine | Out-String)
            Log "SLDPRT conversion exit code: $LASTEXITCODE"
        } catch {
            Log "SLDPRT conversion exception: $($_.Exception.Message)"
        }
    }
} else {
    Log "SLDPRT stage SKIPPED (pyWin=$pyWin, conv exists=$(Test-Path $conv))"
}

# ---------------------------------------------------------------------------
# 6) Result popup  (single component -> <name>_package.step,
#                   multiple components -> <name>_packages\ folder)
# ---------------------------------------------------------------------------
$logPath = Join-Path $dir "jlcto3d_last_run.log"
try { $log | Out-File -FilePath $logPath -Encoding UTF8 } catch { }

if (Test-Path $out) {
    Show-Msg "Done! Clean package saved to:`n`n$out" "JLCTO3D Success"
} elseif (Test-Path $folder) {
    $n = (Get-ChildItem $folder -Filter "*_package.step" -ErrorAction SilentlyContinue | Measure-Object).Count
    Show-Msg "Done! $n components exported separately to:`n`n$folder" "JLCTO3D Success"
} else {
    Show-Msg "Failed. Please check:`n- The source is a JLC EDA exported STEP containing a PCB`n- FreeCAD is installed ($FC)`n`nLog: $logPath" "JLCTO3D Failed"
}
