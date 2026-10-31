# 创建（或重建）桌面快捷方式；可选加入开机启动。
#
#   powershell -ExecutionPolicy Bypass -File .\install_shortcut.ps1
#   powershell -ExecutionPolicy Bypass -File .\install_shortcut.ps1 -Startup
param(
    [string]$AppDir = '',
    [string]$Name = '划词翻译',
    [string]$Pythonw = '',
    [switch]$Startup
)

$ErrorActionPreference = 'Stop'

if (-not $AppDir) { $AppDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
$AppDir = (Resolve-Path -LiteralPath $AppDir).Path
$main = Join-Path $AppDir 'main.py'
if (-not (Test-Path -LiteralPath $main)) {
    throw "找不到主程序：$main"
}

function Find-Exe([string]$exeName) {
    $cmd = Get-Command $exeName -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $patterns = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python*\$exeName"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python*\Scripts\$exeName"),
        (Join-Path $env:ProgramFiles "Python*\$exeName"),
        (Join-Path $env:ProgramFiles "Python*\Scripts\$exeName")
    )
    foreach ($pattern in $patterns) {
        $hit = Get-Item $pattern -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    foreach ($root in @('HKCU:\Software\Python\PythonCore', 'HKLM:\Software\Python\PythonCore')) {
        if (-not (Test-Path $root)) { continue }
        $install = Get-ChildItem $root -ErrorAction SilentlyContinue |
            ForEach-Object { Join-Path $_.PSPath 'InstallPath' } |
            Where-Object { Test-Path $_ } |
            ForEach-Object { (Get-ItemProperty $_).'(default)' } |
            Where-Object { $_ } |
            Select-Object -First 1
        if ($install) {
            $candidate = Join-Path $install $exeName
            if (Test-Path -LiteralPath $candidate) { return $candidate }
        }
    }
    return $null
}

if (-not $Pythonw) {
    $Pythonw = Find-Exe 'pythonw.exe'
    if (-not $Pythonw) { $Pythonw = Find-Exe 'pyw.exe' }
}
if (-not $Pythonw -or -not (Test-Path -LiteralPath $Pythonw)) {
    throw '未找到 pythonw.exe / pyw.exe。请先安装 Python 3.10+，或用 -Pythonw 指定完整路径。'
}

# 快捷方式图标需要 assets\app.ico，缺失时先生成
$iconPath = Join-Path $AppDir 'assets\app.ico'
if (-not (Test-Path -LiteralPath $iconPath)) {
    $python = Find-Exe 'python.exe'
    if ($python) {
        & $python (Join-Path $AppDir 'tools\make_icons.py') (Join-Path $AppDir 'assets')
    }
}

$desktop = [Environment]::GetFolderPath('Desktop')
$lnkPath = Join-Path $desktop "$Name.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($lnkPath)
$shortcut.TargetPath = $Pythonw
$shortcut.Arguments = '"' + $main + '"'
$shortcut.WorkingDirectory = $AppDir
if (Test-Path -LiteralPath $iconPath) { $shortcut.IconLocation = "$iconPath,0" }
$shortcut.Description = '划词翻译：选中英文自动翻译成中文'
$shortcut.WindowStyle = 1
$shortcut.Save()

Write-Host "已创建桌面快捷方式：$lnkPath"
Write-Host "目标：$Pythonw `"$main`""

if ($Startup) {
    $startupDir = [Environment]::GetFolderPath('Startup')
    Copy-Item -LiteralPath $lnkPath -Destination (Join-Path $startupDir "$Name.lnk") -Force
    Write-Host "已加入开机启动：$startupDir"
}
