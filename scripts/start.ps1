#! /usr/bin/pwsh

& "$PSScriptRoot/compile_resources.ps1"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$AppEntryPoint = Join-Path -Path $ProjectRoot -ChildPath "src" -AdditionalChildPath "App.py"
uv run --active "$AppEntryPoint"
