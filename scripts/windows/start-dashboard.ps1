#Requires -Version 5.1
<#
.SYNOPSIS
    Sobe o painel local do JOBOS (python -m jobos serve) em uma janela minimizada e abre a janela do aplicativo.

.DESCRIPTION
    - Porta padrão lida de config\app.yaml (server.port; padrão 8776).
    - Se a porta já estiver em uso, mostra o processo dono (nome e PID) e sai com código 5, sem encerrar nada.
    - Caso contrário inicia o servidor em 127.0.0.1, aguarda até 20 s por /api/health e abre
      http://127.0.0.1:<porta>/painel/ como janela de aplicativo (Edge ou Chrome --app).
    - Se a porta já for o JOBOS (health com service jobos-local), só abre a janela e sai com 0.
    - O servidor roda na janela minimizada: fechar essa janela encerra o painel.
      Fechar a janela do aplicativo não encerra o servidor.

    Códigos de saída: 0 painel no ar, 3 falha ao subir, 5 porta ocupada ou configuração necessária.

.PARAMETER Root
    Raiz do engine (padrão: dois níveis acima deste script).

.PARAMETER Port
    Porta TCP (padrão: server.port do app.yaml, ou 8776).

.PARAMETER NoBrowser
    Não abre a janela.

.PARAMETER Browser
    Abre uma aba no navegador padrão, em vez da janela de aplicativo.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\start-dashboard.ps1"
#>
[CmdletBinding()]
param(
    [string]$Root,

    [ValidateRange(1, 65535)]
    [int]$Port,

    [switch]$NoBrowser,

    [switch]$Browser
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

function Test-Health {
    param([string]$Url)
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2 -ErrorAction Stop
        return ($r.StatusCode -eq 200)
    }
    catch { return $false }
}

function Test-JobosHealth {
    param([string]$Url)
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2 -ErrorAction Stop
        return ($r.StatusCode -eq 200 -and [string]$r.Content -match 'jobos-local')
    }
    catch { return $false }
}

function Get-AppBrowser {
    $bases = @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA)
    $rels = @(
        'Microsoft\Edge\Application\msedge.exe',
        'Google\Chrome\Application\chrome.exe'
    )
    foreach ($rel in $rels) {
        foreach ($base in $bases) {
            if ([string]::IsNullOrWhiteSpace($base)) { continue }
            $path = Join-Path $base $rel
            if (Test-Path -LiteralPath $path -PathType Leaf) { return $path }
        }
    }
    return $null
}

function Open-Panel {
    param(
        [Parameter(Mandatory)][string]$Url,
        [switch]$BrowserTab,
        [switch]$Quiet
    )
    if ($Quiet) { return }
    if ($BrowserTab) {
        Start-Process -FilePath $Url
        Write-Host "Aberto no navegador: $Url"
        return
    }
    $browser = Get-AppBrowser
    if ($browser) {
        Start-Process -FilePath $browser -ArgumentList @("--app=$Url")
        Write-Host "Aberto como aplicativo: $Url"
        Write-Host "Fechar a janela do aplicativo não encerra o servidor. O servidor continua na janela minimizada."
        return
    }
    Start-Process -FilePath $Url
    Write-Host "Edge e Chrome não foram encontrados. Aberto no navegador: $Url"
}

function Get-PortOwners {
    # Retorna objetos {Id, Name, Path} dos donos de sockets em escuta na porta. Lista vazia se livre.
    param([int]$TcpPort)
    $owners = @()
    try {
        $conns = @(Get-NetTCPConnection -LocalPort $TcpPort -State Listen -ErrorAction SilentlyContinue)
        foreach ($ownerId in @($conns | Select-Object -ExpandProperty OwningProcess -Unique)) {
            $p = Get-Process -Id $ownerId -ErrorAction SilentlyContinue
            $path = $null
            if ($p) { try { $path = $p.Path } catch { $path = $null } }
            $owners += [pscustomobject]@{
                Id   = $ownerId
                Name = $(if ($p) { $p.ProcessName } else { '(não identificado)' })
                Path = $path
            }
        }
    }
    catch {
        # alternativa sem PID, caso o módulo NetTCPIP falhe
        $busy = @([System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners() |
                Where-Object { $_.Port -eq $TcpPort })
        if ($busy.Count -gt 0) {
            $owners += [pscustomobject]@{ Id = 0; Name = '(desconhecido: Get-NetTCPConnection indisponível)'; Path = $null }
        }
    }
    return $owners
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

        $cfg = Get-AppConfig -EngineRoot $engineRoot
        $tcpPort = $(if ($PSBoundParameters.ContainsKey('Port')) { $Port } else { [int]$cfg.Port })
        $url = "http://127.0.0.1:$tcpPort/painel/"
        $health = "http://127.0.0.1:$tcpPort/api/health"

        Write-Host '=== JOBOS painel ==='
        Write-Host ('Raiz  : {0}' -f $engineRoot)
        Write-Host ('Porta : {0}' -f $tcpPort)

        $owners = @(Get-PortOwners -TcpPort $tcpPort)
        if ($owners.Count -gt 0) {
            if (Test-JobosHealth -Url $health) {
                Write-Host "O painel JOBOS já está em execução: $url"
                Open-Panel -Url $url -BrowserTab:$Browser -Quiet:$NoBrowser
                $script:ExitCode = 0
                return
            }
            Write-Err ('ERRO: a porta {0} já está em uso e não respondeu como JOBOS. Nada foi encerrado.' -f $tcpPort)
            foreach ($o in $owners) {
                $extra = $(if ($o.Path) { ' - ' + $o.Path } else { '' })
                Write-Err ('       processo: {0} (PID {1}){2}' -f $o.Name, $o.Id, $extra)
            }
            Write-Host 'Use -Port com outra porta, ou encerre o processo acima por conta própria.'
            $script:ExitCode = 5
            return
        }

        $saved = Set-EngineEnv -EngineRoot $engineRoot
        $serveArgs = @('-m', 'jobos', 'serve', '--host', '127.0.0.1', '--port', [string]$tcpPort)
        $quoted = @($serveArgs | ForEach-Object { Format-NativeArg -Value $_ })

        Write-Host 'Iniciando o servidor em uma janela minimizada...'
        $proc = Start-Process -FilePath $py -ArgumentList $quoted -WorkingDirectory $engineRoot -WindowStyle Minimized -PassThru

        $ready = $false
        $deadline = (Get-Date).AddSeconds(20)
        while ((Get-Date) -lt $deadline) {
            if ($proc.HasExited) { break }
            if (Test-Health -Url $health) { $ready = $true; break }
            Start-Sleep -Milliseconds 500
        }

        if ($ready) {
            Write-Host ''
            Write-Host "Painel no ar: $url"
            Write-Host ('Processo iniciado: PID {0}. Para encerrar o servidor, feche a janela minimizada.' -f $proc.Id)
            Write-Host ('Se precisar localizar o dono da porta: (Get-NetTCPConnection -LocalPort {0} -State Listen).OwningProcess' -f $tcpPort)
            Open-Panel -Url $url -BrowserTab:$Browser -Quiet:$NoBrowser
            $script:ExitCode = 0
            return
        }

        if ($proc.HasExited) {
            $exit = $proc.ExitCode
            Write-Err ('ERRO: o servidor terminou antes de responder (código {0}).' -f $exit)
            # diagnóstico sem efeitos colaterais: tenta apenas importar a API
            try {
                $diag = Invoke-Native -File $py -Arguments @('-I', '-B', '-c', 'import jobos.api.app') -WorkingDirectory $engineRoot
                if ($diag.ExitCode -ne 0) {
                    Write-Err '       diagnóstico (import jobos.api.app falhou):'
                    foreach ($l in @($diag.StdErr -split "\r?\n" | Where-Object { $_ } | Select-Object -Last 8)) { Write-Err ('       ' + $l) }
                }
            }
            catch { }
            Write-Err ('       Para ver a mensagem completa, rode em primeiro plano: & "{0}" -m jobos serve' -f $py)
            $script:ExitCode = $(if ($exit -is [int] -and $exit -ne 0) { $exit } else { 3 })
            return
        }

        Write-Err ('ERRO: o servidor não respondeu em {0} após 20 s (PID {1} ainda ativo; não foi encerrado).' -f $health, $proc.Id)
        Write-Err "       Tente abrir $url manualmente ou verifique a janela minimizada."
        $script:ExitCode = 3
    }
    catch {
        Write-Err ('ERRO inesperado: {0} (linha {1})' -f $_.Exception.Message, $_.InvocationInfo.ScriptLineNumber)
        $script:ExitCode = 3
    }
    finally {
        Restore-EngineEnv -Saved $saved
    }
}

Invoke-Main
exit $script:ExitCode
