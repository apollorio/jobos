#Requires -Version 5.1
<#
.SYNOPSIS
    Executa um ciclo único do JOBOS (python -m jobos cycle) e grava o log diário.

.DESCRIPTION
    Usa sempre o Python do venv do app (.venv\Scripts\python.exe), nunca o "python" do PATH.
    A saída do app (stdout e stderr) é anexada, linha a linha com carimbo de data/hora, em
    data\logs\run-cycle-AAAA-MM-DD.log (data no horário local). O carimbo é o momento da gravação
    no log (fim da execução). A linha-resumo do app (run_id=... status=... código=...) fica no log.

    Códigos de saída (propagados do app): 0 ok, 2 parcial, 3 falha, 4 pulado por sobreposição,
    5 configuração necessária (por exemplo, .venv ausente).

.PARAMETER Root
    Raiz do engine (padrão: dois níveis acima deste script). Precisa conter pyproject.toml e src\jobos.

.PARAMETER Mode
    manual (padrão) ou scheduler.

.PARAMETER DryRun
    Repassa --dry-run (banco temporário; nada real é alterado ou enviado).

.PARAMETER NoNotify
    Repassa --no-notify (não enfileira resumo).

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\run-cycle.ps1" -Mode manual -DryRun
#>
[CmdletBinding()]
param(
    [string]$Root,

    [ValidateSet('manual', 'scheduler')]
    [string]$Mode = 'manual',

    [switch]$DryRun,

    [switch]$NoNotify
)

Set-StrictMode -Version 1.0
$ErrorActionPreference = 'Stop'

$script:ExitCode = 3
$script:LogFile = $null
$script:Inv = [System.Globalization.CultureInfo]::InvariantCulture
$script:Utf8Bom = New-Object System.Text.UTF8Encoding($true)

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

function Get-Stamp {
    return (Get-Date).ToString('yyyy-MM-dd HH:mm:ss', $script:Inv)
}

function Add-LogLines {
    param([string[]]$Lines)
    if ($null -eq $script:LogFile -or $Lines.Count -eq 0) { return }
    $text = ($Lines -join [Environment]::NewLine) + [Environment]::NewLine
    for ($i = 1; $i -le 5; $i++) {
        try {
            [System.IO.File]::AppendAllText($script:LogFile, $text, $script:Utf8Bom)
            return
        }
        catch [System.IO.IOException] {
            if ($i -eq 5) { Write-Err ("AVISO: não foi possível gravar no log {0}: {1}" -f $script:LogFile, $_.Exception.Message) }
            else { Start-Sleep -Milliseconds (150 * $i) }
        }
    }
}

function Write-Log {
    param([string]$Message)
    $line = '{0} {1}' -f (Get-Stamp), $Message
    Add-LogLines -Lines @($line)
    Write-Host $line
}

# --------------------------------------------------------------------------- principal

function Invoke-Main {
    $saved = $null
    $tmpOut = $null
    $tmpErr = $null
    try {
        try { $engineRoot = Resolve-EngineRoot -Candidate $Root }
        catch {
            Write-Err ('ERRO: ' + $_.Exception.Message)
            $script:ExitCode = 5
            return
        }

        $logDir = Join-Path $engineRoot 'data\logs'
        [void](New-Item -ItemType Directory -Path $logDir -Force)
        $script:LogFile = Join-Path $logDir ('run-cycle-{0}.log' -f (Get-Date).ToString('yyyy-MM-dd', $script:Inv))
        $py = Join-Path $engineRoot '.venv\Scripts\python.exe'

        if (-not (Test-Path -LiteralPath $py -PathType Leaf)) {
            Write-Log "[ERRO] Python do app ausente: $py. Execute scripts\windows\bootstrap.ps1 (código 5)."
            $script:ExitCode = 5
            return
        }

        $saved = Set-EngineEnv -EngineRoot $engineRoot

        $cycleArgs = @('-m', 'jobos', 'cycle', '--mode', $Mode)
        if ($DryRun) { $cycleArgs += '--dry-run' }
        if ($NoNotify) { $cycleArgs += '--no-notify' }
        $quoted = @($cycleArgs | ForEach-Object { Format-NativeArg -Value $_ })

        $tmpDir = [System.IO.Path]::GetTempPath()
        $tmpOut = Join-Path $tmpDir ('jobos-cycle-{0}.out' -f [guid]::NewGuid().ToString('N'))
        $tmpErr = Join-Path $tmpDir ('jobos-cycle-{0}.err' -f [guid]::NewGuid().ToString('N'))

        Write-Log ('[INICIO] modo={0} dry_run={1} no_notify={2} usuario={3}' -f $Mode, [bool]$DryRun, [bool]$NoNotify, $env:USERNAME)
        Write-Log ('[CMD] "{0}" {1} (cwd={2})' -f $py, ($quoted -join ' '), $engineRoot)

        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        $code = $null
        try {
            $proc = Start-Process -FilePath $py -ArgumentList $quoted -WorkingDirectory $engineRoot `
                -NoNewWindow -Wait -PassThru -RedirectStandardOutput $tmpOut -RedirectStandardError $tmpErr
            $proc.WaitForExit()
            $code = $proc.ExitCode
        }
        catch {
            Write-Log ('[ERRO] falha ao iniciar o Python do app: ' + $_.Exception.Message)
            $script:ExitCode = 3
            return
        }
        $sw.Stop()

        $outLines = @()
        $errLines = @()
        if (Test-Path -LiteralPath $tmpOut) { $outLines = @(Get-Content -LiteralPath $tmpOut -Encoding UTF8 -ErrorAction SilentlyContinue) }
        if (Test-Path -LiteralPath $tmpErr) { $errLines = @(Get-Content -LiteralPath $tmpErr -Encoding UTF8 -ErrorAction SilentlyContinue) }

        $stamp = Get-Stamp
        $logLines = New-Object System.Collections.Generic.List[string]
        foreach ($l in $outLines) {
            $logLines.Add(('{0} [out] {1}' -f $stamp, $l))
            Write-Host $l
        }
        foreach ($l in $errLines) {
            $logLines.Add(('{0} [err] {1}' -f $stamp, $l))
            Write-Err $l
        }
        if ($outLines.Count -eq 0 -and $errLines.Count -eq 0) {
            $logLines.Add(('{0} [aviso] o app não imprimiu nada' -f $stamp))
        }
        Add-LogLines -Lines $logLines.ToArray()

        if ($null -eq $code) {
            Write-Log '[ERRO] não foi possível obter o código de saída do app; assumindo 3.'
            $code = 3
        }
        Write-Log ('[FIM] codigo_saida={0} duracao={1}s' -f $code, $sw.Elapsed.TotalSeconds.ToString('0.0', $script:Inv))
        $script:ExitCode = [int]$code
    }
    catch {
        Write-Log ('[ERRO] inesperado: ' + $_.Exception.Message)
        $script:ExitCode = 3
    }
    finally {
        foreach ($f in @($tmpOut, $tmpErr)) {
            if ($f) { Remove-Item -LiteralPath $f -Force -ErrorAction SilentlyContinue }
        }
        Restore-EngineEnv -Saved $saved
    }
}

Invoke-Main
exit $script:ExitCode
