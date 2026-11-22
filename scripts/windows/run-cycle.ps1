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

    No modo scheduler, sem -DryRun, um ciclo completo com menos de 90 min é pulado (código 0).
    90 min cabe entre os horários de 12:00 e 14:00. Uma repetição por logon ou retorno da suspensão não dispara outra varredura em cima da que acabou de rodar.
    Manual e dry-run sempre seguem. O processo do Python é encerrado no execution_limit_minutes
    do app.yaml (padrão 50); o próprio ciclo para de despachar fontes aos 45 min.

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

    [switch]$NoNotify,

    [switch]$ProbeExitCode
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

function Resolve-AppExitCode {
    # WaitForExit(ms) no PowerShell 5.1 devolve o controle com ExitCode ainda nulo
    # quando a saída está redirecionada. A segunda espera e o Refresh preenchem o código.
    # Se o handle continuar vazio, vale o "código=N" impresso pelo app. Nulo não vira 3 aqui.
    param(
        $Process,
        [bool]$Finished,
        [string[]]$TextLines
    )
    $code = $null
    if ($Finished -and $null -ne $Process) {
        try { $null = $Process.WaitForExit() } catch { }
        try { $Process.Refresh() } catch { }
        if ($null -ne $Process.ExitCode) { $code = [int]$Process.ExitCode }
    }
    if ($null -eq $code -and $TextLines) {
        $match = [regex]::Match(($TextLines -join "`n"), 'c[oó]digo=(\d+)')
        if ($match.Success) { $code = [int]$match.Groups[1].Value }
    }
    return $code
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

function Get-ExecutionLimitMinutes {
    param([string]$EngineRoot)
    $limit = 50
    $yaml = Join-Path $EngineRoot 'config\app.yaml'
    if (Test-Path -LiteralPath $yaml -PathType Leaf) {
        foreach ($line in @(Get-Content -LiteralPath $yaml -Encoding UTF8)) {
            if ($line -match '^\s+execution_limit_minutes:\s*(\d{1,4})\b') { $limit = [int]$Matches[1] }
        }
    }
    if ($limit -lt 1) { $limit = 50 }
    return $limit
}

function Test-SchedulerShouldSkip {
    # $true = último ciclo completo tem menos de 90 min. Falha da sonda não pula.
    param([string]$EngineRoot, [string]$Python)
    $db = Join-Path $EngineRoot 'data\jobos.sqlite3'
    $probe = Join-Path ([System.IO.Path]::GetTempPath()) ('jobos-fresh-{0}.py' -f [guid]::NewGuid().ToString('N'))
    $py = @'
import sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path
db = Path(sys.argv[1])
if not db.is_file():
    print("none")
    raise SystemExit(0)
con = sqlite3.connect("file:" + db.as_posix() + "?mode=ro", uri=True)
try:
    row = con.execute("SELECT finished_at FROM runs WHERE mode='normal' AND status='complete' ORDER BY finished_at DESC LIMIT 1").fetchone()
finally:
    con.close()
if not row or not row[0]:
    print("none")
    raise SystemExit(0)
raw = str(row[0]).replace("Z", "+00:00")
try:
    t = datetime.fromisoformat(raw)
except ValueError:
    print("bad")
    raise SystemExit(0)
if t.tzinfo is None:
    t = t.replace(tzinfo=timezone.utc)
age = (datetime.now(timezone.utc) - t.astimezone(timezone.utc)).total_seconds()
print(str(int(age)))
'@
    try {
        [System.IO.File]::WriteAllText($probe, $py, $script:Utf8Bom)
        $out = & $Python $probe $db 2>&1
        $text = ((@($out) | ForEach-Object { "$_" }) -join ' ').Trim()
        if ($text -match '^\d+$') {
            $age = [int]$Matches[0]
            if ($age -ge 0 -and $age -lt (90 * 60)) {
                Write-Log ("[PULADO] ultimo ciclo completo ha {0}s (< 90 min). Modo scheduler nao repete." -f $age)
                return $true
            }
            Write-Log ("[FRESCO] ultimo ciclo completo ha {0}s; segue." -f $age)
        }
        else {
            Write-Log ("[AVISO] sonda de frescor inconclusiva ({0}); o ciclo segue." -f $text)
        }
    }
    catch {
        Write-Log ('[AVISO] sonda de frescor falhou (' + $_.Exception.Message + '); o ciclo segue.')
    }
    finally {
        if ($probe -and (Test-Path -LiteralPath $probe)) { Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue }
    }
    return $false
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

        if ($Mode -eq 'scheduler' -and -not $DryRun) {
            if (Test-SchedulerShouldSkip -EngineRoot $engineRoot -Python $py) {
                $script:ExitCode = 0
                return
            }
        }
        $limitMin = Get-ExecutionLimitMinutes -EngineRoot $engineRoot

        $saved = Set-EngineEnv -EngineRoot $engineRoot

        $cycleArgs = @('-m', 'jobos', 'cycle', '--mode', $Mode)
        if ($DryRun) { $cycleArgs += '--dry-run' }
        if ($NoNotify) { $cycleArgs += '--no-notify' }
        $quoted = @($cycleArgs | ForEach-Object { Format-NativeArg -Value $_ })

        $tmpDir = [System.IO.Path]::GetTempPath()
        $tmpOut = Join-Path $tmpDir ('jobos-cycle-{0}.out' -f [guid]::NewGuid().ToString('N'))
        $tmpErr = Join-Path $tmpDir ('jobos-cycle-{0}.err' -f [guid]::NewGuid().ToString('N'))

        Write-Log ('[INICIO] modo={0} dry_run={1} no_notify={2} usuario={3} limite_min={4}' -f $Mode, [bool]$DryRun, [bool]$NoNotify, $env:USERNAME, $limitMin)
        Write-Log ('[CMD] "{0}" {1} (cwd={2})' -f $py, ($quoted -join ' '), $engineRoot)

        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        $code = $null
        $finished = $false
        try {
            $proc = Start-Process -FilePath $py -ArgumentList $quoted -WorkingDirectory $engineRoot `
                -NoNewWindow -PassThru -RedirectStandardOutput $tmpOut -RedirectStandardError $tmpErr
            # Sem este handle, o PowerShell 5.1 perde ExitCode depois que o processo termina.
            try { $null = $proc.Handle } catch { }
            $finished = $proc.WaitForExit([int]($limitMin * 60 * 1000))
            if (-not $finished) {
                Write-Log ("[PRAZO] o ciclo passou de {0} min. Encerrando o processo antes do limite do Agendador." -f $limitMin)
                try { & "$env:SystemRoot\System32\taskkill.exe" /PID $proc.Id /T /F | Out-Null } catch { }
                try { if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } } catch { }
                $code = 2
            }
            else {
                $code = $null
            }
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

        if ($finished) {
            $code = Resolve-AppExitCode -Process $proc -Finished $true -TextLines @($outLines + $errLines)
        }
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

function Invoke-ExitCodeProbe {
    # Mesmo lançamento do ciclo: saída em arquivo e WaitForExit com prazo.
    # O texto mente (código=9) e o processo sai 2. O wrapper tem de guardar 2.
    $engineRoot = Resolve-EngineRoot -Candidate $Root
    $py = Join-Path $engineRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $py -PathType Leaf)) {
        Write-Err "ERRO: Python do app ausente: $py"
        exit 5
    }
    $id = [guid]::NewGuid().ToString('N')
    $tmpOut = Join-Path ([System.IO.Path]::GetTempPath()) "jobos-probe-$id.out"
    $tmpErr = Join-Path ([System.IO.Path]::GetTempPath()) "jobos-probe-$id.err"
    $probePy = Join-Path ([System.IO.Path]::GetTempPath()) "jobos-probe-$id.py"
    Set-Content -LiteralPath $probePy -Encoding ASCII -Value "print('codigo=9')`r`nraise SystemExit(2)`r`n"
    $proc = Start-Process -FilePath $py -ArgumentList @($probePy) `
        -WorkingDirectory $engineRoot -NoNewWindow -PassThru -RedirectStandardOutput $tmpOut -RedirectStandardError $tmpErr
    try { $null = $proc.Handle } catch { }
    $finished = $proc.WaitForExit(20000)
    $outLines = @()
    $errLines = @()
    if (Test-Path -LiteralPath $tmpOut) { $outLines = @(Get-Content -LiteralPath $tmpOut -Encoding UTF8 -ErrorAction SilentlyContinue) }
    if (Test-Path -LiteralPath $tmpErr) { $errLines = @(Get-Content -LiteralPath $tmpErr -Encoding UTF8 -ErrorAction SilentlyContinue) }
    Remove-Item -LiteralPath $tmpOut, $tmpErr, $probePy -Force -ErrorAction SilentlyContinue
    $code = $null
    if ($finished) {
        $code = Resolve-AppExitCode -Process $proc -Finished $true -TextLines @($outLines + $errLines)
    }
    if ($null -eq $code) {
        Write-Err 'probe sem codigo'
        exit 3
    }
    Write-Output "probe_exit $code"
    exit ([int]$code)
}

if ($ProbeExitCode) { Invoke-ExitCodeProbe }
Invoke-Main
exit $script:ExitCode
