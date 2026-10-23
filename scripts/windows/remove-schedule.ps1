#Requires -Version 5.1
<#
.SYNOPSIS
    Remove a tarefa agendada do JOBOS (somente a de nome JOBOS*), com backup em XML antes.

.DESCRIPTION
    Exporta o XML da tarefa para data\backups\scheduler\<TaskName>-<timestamp>.xml e então executa
    Unregister-ScheduledTask apenas para esse nome (TaskPath \). Recusa nomes que não comecem com 'JOBOS'
    (maiúsculas) e os nomes protegidos: as tarefas legadas 'jobos-vagas - ciclo 12h' / 'jobos-vagas - ciclo 18h'
    e 'RVALLE-Correios-Jobos-1530'. A ação é registrada em data\backups\scheduler\actions.log.
    Aceita -WhatIf (somente mostra o que seria feito) e -Confirm.

    Códigos de saída: 0 ok (ou tarefa inexistente), 3 falha, 5 nome recusado ou configuração inválida.

.PARAMETER Root
    Raiz do engine (padrão: dois níveis acima deste script).

.PARAMETER TaskName
    Nome da tarefa a remover (padrão: schedule.task_name do app.yaml).

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\remove-schedule.ps1" -WhatIf
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Root,
    [string]$TaskName
)

Set-StrictMode -Version 1.0
$ErrorActionPreference = 'Stop'

$script:ExitCode = 3
$script:Inv = [System.Globalization.CultureInfo]::InvariantCulture
$script:LegacyNames = @('jobos-vagas - ciclo 12h', 'jobos-vagas - ciclo 18h')
$script:NeverTouch = @('RVALLE-Correios-Jobos-1530')

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

function Test-OwnTaskName {
    # Retorna $null se o nome é aceitável; caso contrário, o motivo da recusa.
    param([string]$Name)
    if ([string]::IsNullOrWhiteSpace($Name)) { return 'nome vazio' }
    if ($Name.Length -gt 100) { return 'nome longo demais (máximo 100)' }
    if ($Name -cnotlike 'JOBOS*') { return "o nome precisa começar com 'JOBOS' (maiúsculas)" }
    if ($Name -notmatch '^[A-Za-z0-9][A-Za-z0-9 ._-]*$') { return 'caracteres não permitidos (use letras, números, espaço, ponto, hífen e sublinhado)' }
    foreach ($n in ($script:LegacyNames + $script:NeverTouch)) {
        if ($Name -ieq $n) { return "o nome '$n' é protegido por este script" }
    }
    return $null
}

function Get-Stamp {
    return (Get-Date).ToString('yyyy-MM-dd HH:mm:ss', $script:Inv)
}

# --------------------------------------------------------------------------- principal

function Invoke-Main {
    try {
        try { $engineRoot = Resolve-EngineRoot -Candidate $Root }
        catch {
            Write-Err ('ERRO: ' + $_.Exception.Message)
            $script:ExitCode = 5
            return
        }

        $cfg = Get-AppConfig -EngineRoot $engineRoot
        $name = $(if ([string]::IsNullOrWhiteSpace($TaskName)) { [string]$cfg.TaskName } else { $TaskName })
        $why = Test-OwnTaskName -Name $name
        if ($why) {
            Write-Err ("ERRO: nome de tarefa recusado ('{0}'): {1}" -f $name, $why)
            $script:ExitCode = 5
            return
        }

        Write-Host '=== JOBOS remove-schedule ==='
        if ($WhatIfPreference) { Write-Host '*** MODO -WhatIf: nada será alterado ***' }
        Write-Host ('Tarefa : \{0}' -f $name)

        $task = Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction SilentlyContinue
        if (-not $task) {
            Write-Host 'A tarefa não existe no Agendador (TaskPath \). Nada a fazer.'
            $script:ExitCode = 0
            return
        }

        $backupDir = Join-Path $engineRoot 'data\backups\scheduler'
        if ($PSCmdlet.ShouldProcess("\$name", 'Exportar XML de backup e REMOVER a tarefa (Unregister-ScheduledTask)')) {
            [void](New-Item -ItemType Directory -Path $backupDir -Force)
            $safe = ($task.TaskName -replace '[^\w\.\- ]', '_')
            $file = Join-Path $backupDir ('{0}-{1}.xml' -f $safe, (Get-Date).ToString('yyyyMMdd-HHmmss', $script:Inv))
            $xml = Export-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath
            [System.IO.File]::WriteAllText($file, [string]$xml, [System.Text.Encoding]::Unicode)
            Write-Host ('Backup XML: {0}' -f $file)

            Unregister-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath -Confirm:$false

            $line = '{0} | {1} | UNREGISTER tarefa=''\{2}'' backup=''{3}''' -f (Get-Stamp), $env:USERNAME, $name, $file
            [System.IO.File]::AppendAllText((Join-Path $backupDir 'actions.log'), $line + [Environment]::NewLine, (New-Object System.Text.UTF8Encoding($true)))
            Write-Host ("Tarefa '{0}' removida. Para restaurar: Register-ScheduledTask -TaskName '{0}' -Xml (Get-Content -Raw -LiteralPath '{1}')" -f $name, $file)
        }
        else {
            Write-Host ('WhatIf: a tarefa (estado {0}) seria exportada para {1} e removida. Nada foi alterado.' -f $task.State, $backupDir)
        }
        Write-Host 'Nenhuma outra tarefa do Agendador foi tocada.'
        $script:ExitCode = 0
    }
    catch {
        Write-Err ('ERRO: {0} (linha {1})' -f $_.Exception.Message, $_.InvocationInfo.ScriptLineNumber)
        $script:ExitCode = 3
    }
}

Invoke-Main
exit $script:ExitCode
