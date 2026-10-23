#Requires -Version 5.1
<#
.SYNOPSIS
    Gera um backup consistente do banco do JOBOS (python -m jobos backup --label <Label>).

.DESCRIPTION
    Usa o Python do venv. Mostra a saída do app e propaga o código de saída dele
    (0 ok, 3 falha de integridade/restauração, 5 configuração necessária).

.PARAMETER Root
    Raiz do engine (padrão: dois níveis acima deste script).

.PARAMETER Label
    Rótulo do backup (padrão: manual). Aceita letras, números, ponto, hífen e sublinhado (máx. 60).

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\backup.ps1" -Label antes-da-mudanca
#>
[CmdletBinding()]
param(
    [string]$Root,

    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,59}$')]
    [string]$Label = 'manual'
)

Set-StrictMode -Version 1.0
$ErrorActionPreference = 'Stop'

$script:ExitCode = 3

# --------------------------------------------------------------------------- utilitários

function Write-Err {
    param([string]$Message)
    [Console]::Error.WriteLine($Message)
}

function Resolve-EngineRoot {
    param([string]$Candidate)
    if ([string]::IsNullOrWhiteSpace($Candidate)) { $Candidate = Join-Path $PSScriptRoot '..\..' }
    $resolved = (Resolve-Path -LiteralPath $Candidate -ErrorAction Stop).Path
    if (-not (Test-Path -LiteralPath (Join-Path $resolved 'pyproject.toml') -PathType Leaf) -or
        -not (Test-Path -LiteralPath (Join-Path $resolved 'src\jobos') -PathType Container)) {
        throw "Raiz inválida (faltam pyproject.toml e src\jobos): $resolved"
    }
    return $resolved
}

function Format-NativeArg {
    param([AllowEmptyString()][string]$Value)
    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') { return $Value }
    $escaped = $Value -replace '(\\*)"', '$1$1\"'
    $escaped = $escaped -replace '(\\+)$', '$1$1'
    return '"' + $escaped + '"'
}

function Invoke-Native {
    param(
        [Parameter(Mandatory)][string]$File,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory
    )
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $File
    $psi.Arguments = (@($Arguments | ForEach-Object { Format-NativeArg -Value $_ }) -join ' ')
    if ($WorkingDirectory) { $psi.WorkingDirectory = $WorkingDirectory }
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    [void]$proc.Start()
    $outTask = $proc.StandardOutput.ReadToEndAsync()
    $errTask = $proc.StandardError.ReadToEndAsync()
    $proc.WaitForExit()
    return [pscustomobject]@{ ExitCode = $proc.ExitCode; StdOut = $outTask.Result; StdErr = $errTask.Result }
}

function Set-EngineEnv {
    param([string]$EngineRoot)
    $wanted = [ordered]@{ PYTHONUTF8 = '1'; PYTHONIOENCODING = 'utf-8'; JOBOS_ROOT = $EngineRoot }
    $saved = @{}
    foreach ($key in $wanted.Keys) {
        $saved[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
        [Environment]::SetEnvironmentVariable($key, $wanted[$key], 'Process')
    }
    return $saved
}

function Restore-EngineEnv {
    param($Saved)
    if ($null -eq $Saved) { return }
    foreach ($key in @($Saved.Keys)) {
        [Environment]::SetEnvironmentVariable($key, $Saved[$key], 'Process')
    }
}

# --------------------------------------------------------------------------- principal

function Invoke-Main {
    $saved = $null
    try {
        try { $engineRoot = Resolve-EngineRoot -Candidate $Root }
        catch {
            Write-Err ('ERRO: ' + $_.Exception.Message)
            $script:ExitCode = 5
            return
        }
        $py = Join-Path $engineRoot '.venv\Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $py -PathType Leaf)) {
            Write-Err "ERRO: Python do app ausente: $py. Execute scripts\windows\bootstrap.ps1."
            $script:ExitCode = 5
            return
        }
        $saved = Set-EngineEnv -EngineRoot $engineRoot
        Write-Host ('=== JOBOS backup (rótulo: {0}) ===' -f $Label)
        $r = Invoke-Native -File $py -Arguments @('-m', 'jobos', 'backup', '--label', $Label) -WorkingDirectory $engineRoot
        foreach ($l in @($r.StdOut -split "\r?\n")) { if ($l -ne '') { Write-Host $l } }
        foreach ($l in @($r.StdErr -split "\r?\n")) { if ($l -ne '') { Write-Err ('[stderr] ' + $l) } }
        Write-Host ('(jobos backup terminou com código {0})' -f $r.ExitCode)
        $script:ExitCode = [int]$r.ExitCode
    }
    catch {
        Write-Err ('ERRO: {0} (linha {1})' -f $_.Exception.Message, $_.InvocationInfo.ScriptLineNumber)
        $script:ExitCode = 3
    }
    finally {
        Restore-EngineEnv -Saved $saved
    }
}

Invoke-Main
exit $script:ExitCode
