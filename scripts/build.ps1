#! /usr/bin/pwsh

& "$PSScriptRoot/compile_resources.ps1"

$ProjectRoot = "$PSScriptRoot/.."
$SupportsSplashScreen = [System.Convert]::ToBoolean($(uv run --active python -c "import _tkinter; print(hasattr(_tkinter, '__file__'))"))

$arguments = @(
  "$ProjectRoot/src/App.py",
  '--name ZDCurtain'
  '--onefile',
  '--windowed',
  '--optimize=2', # Remove asserts and docstrings for smaller build
  "--additional-hooks-dir=$ProjectRoot/Pyinstaller/hooks",
  # Installed by PyAutoGUI
  '--exclude=pyscreeze',
  # Sometimes installed by other automation/image libraries.
  # Keep this exclusion even if nothing currently installs it, to stay future-proof.
  '--exclude=PIL',
  "--add-data=$ProjectRoot/pyproject.toml$([System.IO.Path]::PathSeparator).",
  "--add-data=$ProjectRoot/res/icons/*.png:res/icons/",
  "--add-data=$ProjectRoot/res/*.ico:res/",
  "--upx-dir=$PSScriptRoot/.upx"
  "--icon=$ProjectRoot/res/icon.ico")
if ($SupportsSplashScreen) {
  # https://github.com/pyinstaller/pyinstaller/issues/9022
  # $arguments += @("--splash=$ProjectRoot/res/splash.png")
}
if ($IsWindows) {
  $arguments += @(
    # Hidden import by winrt.windows.graphics.imaging.SoftwareBitmap.create_copy_from_surface_async
    '--hidden-import=winrt.windows.foundation')
}

Start-Process -Wait -NoNewWindow uv -ArgumentList $(@('run', '--active', 'pyinstaller') + $arguments)

Copy-Item -Path "$ProjectRoot/res/comparison" -Destination "$ProjectRoot/dist" -Recurse -Force

$BUILD_NUMBER = Get-Date -Format yyMMddHHmm

$compress = @{
  Path = "$ProjectRoot/dist/comparison", "$ProjectRoot/dist/ZDCurtain.exe", "$ProjectRoot/README.md"
  CompressionLevel = "Optimal"
  DestinationPath = "$ProjectRoot/dist/ZDCurtain-$BUILD_NUMBER.zip"
}
Compress-Archive @compress
