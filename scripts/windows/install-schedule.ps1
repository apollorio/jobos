#Requires -Version 5.1
<#
.SYNOPSIS
    Registra (ou atualiza) a tarefa agendada "JOBOS Local Engine" com 4 gatilhos diários.

.DESCRIPTION
    Cria UMA tarefa (TaskPath \) com um gatilho diário por horário (padrão do app.yaml: 08:00, 12:00, 14:00, 18:00).
    Ação: powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "<Raiz>\scripts\windows\run-cycle.ps1" -Mode scheduler
    com diretório de trabalho = raiz do engine.

    Configurações: StartWhenAvailable, MultipleInstances IgnoreNew, limite de execução de 50 min (app.yaml),
    roda com bateria. Conta: usuário atual, LogonType Interactive, RunLevel Limited. Ou seja, a tarefa
    executa SOMENTE enquanto o usuário estiver conectado (logado). PC desligado ou suspenso não executa
    tarefas, e WakeToRun NÃO está habilitado (com StartWhenAvailable, a execução perdida roda quando o
    PC voltar e o usuário estiver conectado).

    Idempotente: se a tarefa já existe, exporta o XML para data\backups\scheduler\<TaskName>-<timestamp>.xml
    e a atualiza no lugar (mesmo nome). Só toca na tarefa de nome JOBOS* informada.

    -DisableLegacy: para exatamente as tarefas legadas 'jobos-vagas - ciclo 12h' e 'jobos-vagas - ciclo 18h',
    se existirem, exporta o XML para o mesmo diretório de backup e DESATIVA (Disable-ScheduledTask; nunca
    remove). As ações são registradas em data\backups\scheduler\actions.log. Nenhuma outra tarefa é tocada
    (em especial, nunca 'RVALLE-Correios-Jobos-1530').

    Use -WhatIf para ver apenas o plano, sem alterar nada.

.PARAMETER Root
    Raiz do engine (padrão: dois níveis acima deste script).

.PARAMETER TaskName
    Nome da tarefa (padrão: schedule.task_name do app.yaml). Precisa começar com JOBOS.

.PARAMETER Times
    Horários HH:mm (padrão: schedule.times do app.yaml). Ex.: -Times '08:00','12:00','14:00','18:00'

.PARAMETER DisableLegacy
    Desativa (sem remover) as duas tarefas legadas citadas acima.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\install-schedule.ps1" -WhatIf
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Root,
    [string]$TaskName,
    [string[]]$Times,
    [switch]$DisableLegacy
)

Set-StrictMode -Version 1.0
$ErrorActionPreference = 'Stop'

$script:ExitCode = 3
$script:Inv = [System.Globalization.CultureInfo]::InvariantCulture
$script:LegacyNames = @('jobos-vagas - ciclo 12h', 'jobos-vagas - ciclo 18h')
$script:NeverTouch = @('RVALLE-Correios-Jobos-1530')
$script:ExpectedTz = 'E. South America Standard Time'
$script:ActionsLog = $null

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

function Write-ActionLog {
    param([string]$Message)
    if (-not $script:ActionsLog) { return }
    $line = '{0} | {1} | {2}' -f (Get-Stamp), $env:USERNAME, $Message
    [System.IO.File]::AppendAllText($script:ActionsLog, $line + [Environment]::NewLine, (New-Object System.Text.UTF8Encoding($true)))
}

function Export-TaskBackup {
    # Exporta o XML da tarefa (UTF-16, igual à declaração do XML) e devolve o caminho do arquivo.
    param($Task, [string]$Dir)
    $safe = ($Task.TaskName -replace '[^\w\.\- ]', '_')
    $file = Join-Path $Dir ('{0}-{1}.xml' -f $safe, (Get-Date).ToString('yyyyMMdd-HHmmss', $script:Inv))
    $xml = Export-ScheduledTask -TaskName $Task.TaskName -TaskPath $Task.TaskPath
    [System.IO.File]::WriteAllText($file, [string]$xml, [System.Text.Encoding]::Unicode)
    return $file
}

function Show-TaskSummary {
    param([string]$Name)
    $task = Get-ScheduledTask -TaskName $Name -TaskPath '\' -ErrorAction Stop
    $info = Get-ScheduledTaskInfo -TaskName $Name -TaskPath '\' -ErrorAction Stop
    Write-Host ''
    Write-Host '--- Resumo da tarefa registrada ---'
    Write-Host ('Nome            : \{0}' -f $task.TaskName)
    Write-Host ('Estado          : {0}' -f $task.State)
    $hours = @()
    foreach ($t in @($task.Triggers)) {
        try { $hours += ([datetime]::Parse([string]$t.StartBoundary, $script:Inv)).ToString('HH:mm', $script:Inv) } catch { $hours += '?' }
    }
    Write-Host ('Gatilhos diários: {0}' -f ($hours -join ', '))
    Write-Host ('Próxima execução: {0}' -f $(if ($info.NextRunTime -and $info.NextRunTime.Year -gt 2000) { $info.NextRunTime.ToString('yyyy-MM-dd HH:mm:ss', $script:Inv) } else { '(nenhuma)' }))
    Write-Host ('Última execução : {0}' -f $(if ($info.LastRunTime -and $info.LastRunTime.Year -gt 2000) { $info.LastRunTime.ToString('yyyy-MM-dd HH:mm:ss', $script:Inv) } else { 'nunca executou' }))
    Write-Host ('Último resultado: {0}' -f $info.LastTaskResult)
    Write-Host ('Conta           : {0} (LogonType {1}, RunLevel {2})' -f $task.Principal.UserId, $task.Principal.LogonType, $task.Principal.RunLevel)
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

        # horários
        $rawTimes = $(if ($Times -and $Times.Count -gt 0) { $Times } else { @($cfg.Times) })
        $timeList = @()
        foreach ($item in $rawTimes) {
            foreach ($piece in ([string]$item -split '[,;\s]+')) {
                if ($piece -eq '') { continue }
                if ($piece -notmatch '^([01]?\d|2[0-3]):[0-5]\d$') {
                    Write-Err ("ERRO: horário inválido '{0}' (use HH:mm, 00:00 a 23:59)." -f $piece)
                    $script:ExitCode = 5
                    return
                }
                $norm = [datetime]::ParseExact($piece, 'H:mm', $script:Inv).ToString('HH:mm', $script:Inv)
                if ($timeList -notcontains $norm) { $timeList += $norm }
            }
        }
        if ($timeList.Count -eq 0) {
            Write-Err 'ERRO: nenhum horário informado.'
            $script:ExitCode = 5
            return
        }

        $runCycle = Join-Path $engineRoot 'scripts\windows\run-cycle.ps1'
        if (-not (Test-Path -LiteralPath $runCycle -PathType Leaf)) {
            Write-Err "ERRO: run-cycle.ps1 não encontrado em $runCycle"
            $script:ExitCode = 5
            return
        }
        $py = Join-Path $engineRoot '.venv\Scripts\python.exe'
        $backupDir = Join-Path $engineRoot 'data\backups\scheduler'
        $script:ActionsLog = Join-Path $backupDir 'actions.log'
        $limit = [int]$cfg.LimitMinutes
        $psExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $argString = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" -Mode scheduler' -f $runCycle
        $user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

        Write-Host '=== JOBOS install-schedule ==='
        if ($WhatIfPreference) { Write-Host '*** MODO -WhatIf: apenas o plano, nada será alterado ***' }
        Write-Host ('Raiz              : {0}' -f $engineRoot)
        Write-Host ('Tarefa            : \{0}' -f $name)
        Write-Host ('Horários (diários): {0}' -f ($timeList -join ', '))
        Write-Host ('Ação              : {0} {1}' -f $psExe, $argString)
        Write-Host ('Diretório de trab.: {0}' -f $engineRoot)
        Write-Host ('Conta             : {0} (LogonType Interactive, RunLevel Limited)' -f $user)
        Write-Host '                    A tarefa roda SOMENTE enquanto este usuário estiver conectado (logado).'
        Write-Host ('Configurações     : StartWhenAvailable, MultipleInstances IgnoreNew, limite {0} min, roda na bateria' -f $limit)

        # fuso horário: apenas avisa
        $tz = Get-TimeZone
        if ($tz.Id -ne $script:ExpectedTz) {
            Write-Warning ("O fuso do Windows é '{0}', não '{1}'. Os horários da tarefa seguem o relógio local do Windows; nada foi alterado." -f $tz.Id, $script:ExpectedTz)
        }
        else {
            Write-Host ('Fuso horário      : {0} (ok)' -f $tz.Id)
        }
        if (-not (Test-Path -LiteralPath $py -PathType Leaf)) {
            Write-Warning ('Python do app ausente ({0}). A tarefa falharia com código 5 até rodar bootstrap.ps1.' -f $py)
        }

        # estado atual (somente leitura)
        $existing = Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction SilentlyContinue
        Write-Host ''
        Write-Host '--- Plano ---'
        if ($existing) { Write-Host ("1. Tarefa '{0}' já existe (estado {1}): exportar XML para {2} e atualizar no lugar." -f $name, $existing.State, $backupDir) }
        else { Write-Host ("1. Tarefa '{0}' não existe: registrar nova." -f $name) }

        $legacyFound = @()
        if ($DisableLegacy) {
            foreach ($ln in $script:LegacyNames) {
                $hit = @(Get-ScheduledTask -TaskName $ln -ErrorAction SilentlyContinue | Where-Object { $_.TaskName -ieq $ln })
                if ($hit.Count -eq 0) { Write-Host ("2. Legada '{0}': não encontrada, nada a fazer." -f $ln); continue }
                foreach ($h in $hit) {
                    if ($h.State -eq 'Disabled') { Write-Host ("2. Legada '{0}{1}': já desativada, nada a fazer." -f $h.TaskPath, $h.TaskName) }
                    else {
                        Write-Host ("2. Legada '{0}{1}' (estado {2}): exportar XML e DESATIVAR (não será removida)." -f $h.TaskPath, $h.TaskName, $h.State)
                        $legacyFound += $h
                    }
                }
            }
        }
        else {
            Write-Host '2. Tarefas legadas: não serão tocadas (use -DisableLegacy para desativá-las).'
        }

        # definição da tarefa (objetos em memória)
        $triggers = @()
        foreach ($hhmm in $timeList) {
            $at = [datetime]::ParseExact($hhmm, 'H:mm', $script:Inv)
            $triggers += New-ScheduledTaskTrigger -Daily -At $at
        }
        $action = New-ScheduledTaskAction -Execute $psExe -Argument $argString -WorkingDirectory $engineRoot
        $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
            -ExecutionTimeLimit (New-TimeSpan -Minutes $limit) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
        $definition = New-ScheduledTask -Action $action -Trigger $triggers -Settings $settings -Principal $principal `
            -Description 'JOBOS local: coleta de vagas em ciclos diários (gerenciada por scripts\windows\install-schedule.ps1).'

        # ----------------------------------------------------------- aplica
        $changed = $false
        $opText = $(if ($existing) { 'Exportar XML de backup e atualizar a tarefa' } else { 'Registrar nova tarefa' })
        if ($PSCmdlet.ShouldProcess("\$name", $opText)) {
            [void](New-Item -ItemType Directory -Path $backupDir -Force)
            if ($existing) {
                $bk = Export-TaskBackup -Task $existing -Dir $backupDir
                Write-Host ("Backup XML: {0}" -f $bk)
                Write-ActionLog ("EXPORT tarefa='\{0}' arquivo='{1}'" -f $name, $bk)
            }
            [void](Register-ScheduledTask -TaskName $name -TaskPath '\' -InputObject $definition -Force)
            Write-ActionLog ("{0} tarefa='\{1}' horarios={2} conta='{3}' logon=Interactive runlevel=Limited" -f $(if ($existing) { 'UPDATE' } else { 'REGISTER' }), $name, ($timeList -join ','), $user)
            Write-Host ("Tarefa '{0}' {1}." -f $name, $(if ($existing) { 'atualizada' } else { 'registrada' }))
            $changed = $true
        }

        if ($DisableLegacy) {
            foreach ($lt in $legacyFound) {
                $target = '{0}{1}' -f $lt.TaskPath, $lt.TaskName
                if ($PSCmdlet.ShouldProcess($target, 'Exportar XML de backup e DESATIVAR a tarefa legada')) {
                    [void](New-Item -ItemType Directory -Path $backupDir -Force)
                    $bk = Export-TaskBackup -Task $lt -Dir $backupDir
                    Write-ActionLog ("EXPORT tarefa legada='{0}' arquivo='{1}'" -f $target, $bk)
                    [void](Disable-ScheduledTask -TaskName $lt.TaskName -TaskPath $lt.TaskPath)
                    Write-ActionLog ("DISABLE tarefa legada='{0}' (nao removida)" -f $target)
                    Write-Host ("Legada desativada: {0} (backup: {1})" -f $target, $bk)
                    $changed = $true
                }
            }
        }

        if ($changed -and -not $WhatIfPreference) { Show-TaskSummary -Name $name }
        elseif ($WhatIfPreference) {
            Write-Host ''
            Write-Host 'WhatIf: nada foi alterado.'
        }

        Write-Host ''
        Write-Host 'Observações:'
        Write-Host '  - A tarefa só executa com o usuário conectado (LogonType Interactive).'
        Write-Host '  - PC desligado (ou em suspensão/hibernação) não executa tarefas; WakeToRun NÃO está habilitado.'
        Write-Host '  - StartWhenAvailable: uma execução perdida roda quando o PC voltar e o usuário estiver conectado.'
        Write-Host '  - Nenhuma outra tarefa do Agendador foi tocada.'
        $script:ExitCode = 0
    }
    catch {
        Write-Err ('ERRO: {0} (linha {1})' -f $_.Exception.Message, $_.InvocationInfo.ScriptLineNumber)
        $script:ExitCode = 3
    }
}

Invoke-Main
exit $script:ExitCode
