#Requires -Version 5.1
<#
.SYNOPSIS
    Mostra o estado do Agendador do Windows (JOBOS e tarefas legadas) e o status do engine. Somente leitura.

.DESCRIPTION
    Seção 1, "Agendador do Windows": para 'JOBOS Local Engine' (nome do app.yaml) e para as duas tarefas
    legadas ('jobos-vagas - ciclo 12h' e 'jobos-vagas - ciclo 18h') mostra Estado, última execução,
    último resultado (decimal e hexadecimal), próxima execução. Se a tarefa não existe, informa.
    Seção 2, "Engine": executa "python -m jobos status" com o Python do venv e mostra a saída.

    Não registra, altera, ativa nem desativa tarefas.
    Código de saída: o do "jobos status" (0 ok); 5 se o venv/raiz não estiver pronto.

.PARAMETER Root
    Raiz do engine (padrão: dois níveis acima deste script).

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\show-status.ps1"
#>
[CmdletBinding()]
param(
    [string]$Root
)

Set-StrictMode -Version 1.0
$ErrorActionPreference = 'Stop'

$script:ExitCode = 3
$script:Inv = [System.Globalization.CultureInfo]::InvariantCulture
$script:LegacyNames = @('jobos-vagas - ciclo 12h', 'jobos-vagas - ciclo 18h')
$script:ExpectedTz = 'E. South America Standard Time'

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

function Get-AppConfig {
    # Leitura simples do app.yaml por regex (sem módulo YAML). Valores padrão se não encontrar.
    param([Parameter(Mandatory)][string]$EngineRoot)
    $cfg = @{ Port = 8776; TaskName = 'JOBOS Local Engine'; Times = @('08:00', '12:00', '14:00', '18:00'); LimitMinutes = 50 }
    $yamlPath = Join-Path $EngineRoot 'config\app.yaml'
    if (-not (Test-Path -LiteralPath $yamlPath -PathType Leaf)) { return $cfg }
    try { $lines = @(Get-Content -LiteralPath $yamlPath -Encoding UTF8 -ErrorAction Stop) } catch { return $cfg }
    $section = ''
    foreach ($line in $lines) {
        if ($line -match '^\s*(#|$)') { continue }
        if ($line -match '^([A-Za-z_][\w-]*):\s*(#.*)?$') { $section = $Matches[1]; continue }
        if ($line -match '^\S') { $section = ''; continue }
        if ($section -eq 'server' -and $line -match '^\s+port:\s*(\d{1,5})\b') {
            $p = [int]$Matches[1]
            if ($p -ge 1 -and $p -le 65535) { $cfg.Port = $p }
        }
        elseif ($section -eq 'schedule') {
            if ($line -match '^\s+task_name:\s*(.+?)\s*$') {
                $v = $Matches[1]
                if ($v -match '^"([^"]*)"') { $v = $Matches[1] }
                elseif ($v -match "^'([^']*)'") { $v = $Matches[1] }
                else { $v = ($v -replace '\s+#.*$', '').Trim() }
                if ($v) { $cfg.TaskName = $v }
            }
            elseif ($line -match '^\s+times:\s*\[(.*?)\]') {
                $found = @()
                foreach ($m in [regex]::Matches($Matches[1], '\b([01]?\d|2[0-3]):([0-5]\d)\b')) {
                    $hhmm = '{0:00}:{1}' -f [int]$m.Groups[1].Value, $m.Groups[2].Value
                    if ($found -notcontains $hhmm) { $found += $hhmm }
                }
                if ($found.Count -gt 0) { $cfg.Times = $found }
            }
            elseif ($line -match '^\s+execution_limit_minutes:\s*(\d{1,4})\b') {
                $n = [int]$Matches[1]
                if ($n -ge 1 -and $n -le 1440) { $cfg.LimitMinutes = $n }
            }
        }
    }
    return $cfg
}

function Get-ResultText {
    # Tradução curta do LastTaskResult. Para execuções do JOBOS, o resultado é o código de saída do app.
    param([int64]$Code)
    switch ($Code) {
        0 { return 'sucesso (0)' }
        1 { return 'erro genérico (1)' }
        2 { return 'ciclo parcial (2, código do app)' }
        3 { return 'falha (3, código do app)' }
        4 { return 'pulado por sobreposição (4, código do app)' }
        5 { return 'configuração necessária (5, código do app)' }
        267008 { return 'pronta para executar (0x41300)' }
        267009 { return 'em execução agora (0x41301)' }
        267010 { return 'desativada (0x41302)' }
        267011 { return 'ainda não executou (0x41303)' }
        267014 { return 'encerrada pelo usuário ou pelo limite de tempo (0x41306)' }
        default { return 'consulte a documentação do Agendador para este código' }
    }
}

function Show-TaskBlock {
    param([string]$Name, [string]$Label, [bool]$ShowAction)
    Write-Host ''
    Write-Host ("[{0}] {1}" -f $Label, $Name)
    $hits = @(Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue | Where-Object { $_.TaskName -ieq $Name })
    if ($hits.Count -eq 0) {
        Write-Host '    NÃO ENCONTRADA no Agendador.'
        return
    }
    foreach ($t in $hits) {
        $info = Get-ScheduledTaskInfo -TaskName $t.TaskName -TaskPath $t.TaskPath -ErrorAction Stop
        $raw = [int64]$info.LastTaskResult
        $hex = '0x{0:X8}' -f [uint32]($raw -band 0xFFFFFFFF)
        $last = $(if ($info.LastRunTime -and $info.LastRunTime.Year -gt 2000) { $info.LastRunTime.ToString('yyyy-MM-dd HH:mm:ss', $script:Inv) } else { 'nunca executou' })
        $next = $(if ($info.NextRunTime -and $info.NextRunTime.Year -gt 2000) { $info.NextRunTime.ToString('yyyy-MM-dd HH:mm:ss', $script:Inv) } else { '(sem próxima execução: tarefa desativada ou sem gatilhos)' })
        $hours = @()
        foreach ($tr in @($t.Triggers)) {
            try { $hours += ([datetime]::Parse([string]$tr.StartBoundary, $script:Inv)).ToString('HH:mm', $script:Inv) } catch { $hours += '?' }
        }
        Write-Host ('    Caminho         : {0}{1}' -f $t.TaskPath, $t.TaskName)
        Write-Host ('    Estado          : {0}' -f $t.State)
        Write-Host ('    Última execução : {0}' -f $last)
        Write-Host ('    Último resultado: {0} ({1}) - {2}' -f $raw, $hex, (Get-ResultText -Code $raw))
        Write-Host ('    Próxima execução: {0}' -f $next)
        Write-Host ('    Gatilhos        : {0}' -f $(if ($hours.Count -gt 0) { $hours -join ', ' } else { '(nenhum)' }))
        if ($ShowAction) {
            foreach ($a in @($t.Actions)) {
                Write-Host ('    Ação            : {0} {1}' -f $a.Execute, $a.Arguments)
            }
            Write-Host ('    Conta           : {0} (LogonType {1}, RunLevel {2})' -f $t.Principal.UserId, $t.Principal.LogonType, $t.Principal.RunLevel)
        }
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
        $cfg = Get-AppConfig -EngineRoot $engineRoot

        Write-Host '================================================================'
        Write-Host ' 1. Agendador do Windows'
        Write-Host '================================================================'
        $tz = Get-TimeZone
        Write-Host ('Agora (local)   : {0}' -f (Get-Date).ToString('yyyy-MM-dd HH:mm:ss', $script:Inv))
        Write-Host ('Fuso do Windows : {0}{1}' -f $tz.Id, $(if ($tz.Id -ne $script:ExpectedTz) { "  [AVISO: esperado '$($script:ExpectedTz)']" } else { '' }))

        try {
            Show-TaskBlock -Name ([string]$cfg.TaskName) -Label 'JOBOS' -ShowAction $true
            foreach ($ln in $script:LegacyNames) { Show-TaskBlock -Name $ln -Label 'LEGADA' -ShowAction $false }
        }
        catch {
            Write-Err ('AVISO: não foi possível consultar o Agendador: ' + $_.Exception.Message)
        }

        Write-Host ''
        Write-Host '================================================================'
        Write-Host ' 2. Engine (python -m jobos status)'
        Write-Host '================================================================'
        $py = Join-Path $engineRoot '.venv\Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $py -PathType Leaf)) {
            Write-Err "Python do app ausente: $py. Execute scripts\windows\bootstrap.ps1."
            $script:ExitCode = 5
            return
        }
        $saved = Set-EngineEnv -EngineRoot $engineRoot
        $r = Invoke-Native -File $py -Arguments @('-m', 'jobos', 'status') -WorkingDirectory $engineRoot
        foreach ($l in @($r.StdOut -split "\r?\n")) { if ($l -ne '') { Write-Host $l } }
        foreach ($l in @($r.StdErr -split "\r?\n")) { if ($l -ne '') { Write-Err ('[stderr] ' + $l) } }
        Write-Host ''
        Write-Host ('(jobos status terminou com código {0})' -f $r.ExitCode)
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
