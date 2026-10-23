#Requires -Version 5.1
<#
.SYNOPSIS
    Prepara (ou apenas diagnostica) o ambiente Python do JOBOS: py -3.12, .venv, pacote jobos e doctor.

.DESCRIPTION
    Modo normal (idempotente):
      1. localiza o Python 3.12 base (launcher "py -3.12"; como alternativa, o caminho padrão do Python312);
      2. cria o .venv somente se faltar (com -Recreate, renomeia o antigo para .venv.bak-<timestamp>; nunca apaga);
      3. instala o pacote: requirements.lock (se existir) + "pip install --no-deps -e <Root>",
         ou "pip install -e <Root>[dev]" quando não há lock;
      4. executa "python -m jobos doctor" e sai com o código dele.

    Com -CheckOnly: somente relata o que existe (launcher, python do venv, import de jobos). Não instala,
    não cria, não renomeia e não executa o doctor (ele toca no banco e na trava de ciclo).
    Em -CheckOnly o código de saída é 0 se o ambiente está pronto e 5 se falta algo (rodar sem -CheckOnly).

    Nunca usa o "python" do PATH (neste PC ele aponta para o Python do Inkscape).

.PARAMETER Root
    Raiz do engine (padrão: dois níveis acima deste script).

.PARAMETER CheckOnly
    Somente diagnóstico, sem alterações.

.PARAMETER Recreate
    Renomeia o .venv existente para .venv.bak-<timestamp> e cria um novo. Ignorado com -CheckOnly.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\bootstrap.ps1" -CheckOnly
#>
[CmdletBinding()]
param(
    [string]$Root,
    [switch]$CheckOnly,
    [switch]$Recreate
)

Set-StrictMode -Version 1.0
$ErrorActionPreference = 'Stop'

$script:ExitCode = 3
$script:Inv = [System.Globalization.CultureInfo]::InvariantCulture

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
    # Executa um programa capturando stdout e stderr separadamente (UTF-8), sem ErrorRecord.
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

function Invoke-Live {
    # Executa um programa com a saída direto no console (instalações longas). Devolve o código de saída.
    param(
        [Parameter(Mandatory)][string]$File,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory
    )
    $quoted = @($Arguments | ForEach-Object { Format-NativeArg -Value $_ })
    $p = Start-Process -FilePath $File -ArgumentList $quoted -WorkingDirectory $WorkingDirectory -NoNewWindow -Wait -PassThru
    $p.WaitForExit()
    if ($null -eq $p.ExitCode) { return 3 }
    return [int]$p.ExitCode
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

function Write-NativeOutput {
    param($Result)
    foreach ($l in @($Result.StdOut -split "\r?\n")) { if ($l -ne '') { Write-Host ('      ' + $l) } }
    foreach ($l in @($Result.StdErr -split "\r?\n")) { if ($l -ne '') { Write-Err ('      [stderr] ' + $l) } }
}

function Write-Step {
    param([string]$Text)
    Write-Host ''
    Write-Host $Text
}

function Write-Item {
    param([string]$Label, [string]$Value)
    Write-Host ('      {0,-16}: {1}' -f $Label, $Value)
}

# --------------------------------------------------------------------------- diagnóstico

function Get-BasePython {
    # Procura o Python 3.12 base. Retorna objeto com Found, Exe, Prefix, Version, RealExe, Origin, LauncherPath, Notes.
    $result = [pscustomobject]@{
        Found = $false; Exe = $null; Prefix = @(); Version = $null; RealExe = $null
        Origin = $null; LauncherPath = $null; Notes = (New-Object System.Collections.Generic.List[string])
    }
    $candidates = New-Object System.Collections.Generic.List[object]

    $launcher = Get-Command -Name 'py' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($launcher) {
        $result.LauncherPath = $launcher.Source
        $candidates.Add([pscustomobject]@{ Exe = $launcher.Source; Prefix = @('-3.12'); Origin = 'launcher py -3.12' })
    }
    else {
        $result.Notes.Add('launcher "py" não encontrado no PATH')
    }

    if ($env:LOCALAPPDATA) {
        $fallback = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
        if (Test-Path -LiteralPath $fallback -PathType Leaf) {
            $candidates.Add([pscustomobject]@{ Exe = $fallback; Prefix = @(); Origin = 'caminho padrão do Python 3.12' })
        }
    }

    foreach ($c in $candidates) {
        try {
            $probe = @($c.Prefix) + @('-I', '-B', '-c', 'import sys;print(sys.version.split()[0]);print(sys.executable)')
            $r = Invoke-Native -File $c.Exe -Arguments $probe
            if ($r.ExitCode -ne 0) {
                $first = (@($r.StdErr -split "\r?\n") | Where-Object { $_ } | Select-Object -First 1)
                $result.Notes.Add(("{0}: código {1} {2}" -f $c.Origin, $r.ExitCode, $first))
                continue
            }
            $lines = @($r.StdOut -split "\r?\n" | Where-Object { $_ })
            if ($lines.Count -lt 2) { $result.Notes.Add("$($c.Origin): saída inesperada"); continue }
            $ver = $lines[0].Trim()
            if ($ver -notmatch '^3\.12\.') { $result.Notes.Add("$($c.Origin): versão $ver (esperado 3.12.x)"); continue }
            $result.Found = $true
            $result.Exe = $c.Exe
            $result.Prefix = @($c.Prefix)
            $result.Version = $ver
            $result.RealExe = $lines[1].Trim()
            $result.Origin = $c.Origin
            return $result
        }
        catch {
            $result.Notes.Add(("{0}: {1}" -f $c.Origin, $_.Exception.Message))
        }
    }
    return $result
}

function Get-VenvState {
    param([string]$Py, [string]$EngineRoot)
    $s = [pscustomobject]@{
        Exists = $false; Version = $null; VersionOk = $false
        ImportOk = $false; JobosVersion = $null; JobosFile = $null; Problem = $null
    }
    if (-not (Test-Path -LiteralPath $Py -PathType Leaf)) { return $s }
    $s.Exists = $true
    try {
        $r = Invoke-Native -File $Py -Arguments @('-I', '-B', '-c', 'import sys;print(sys.version.split()[0])') -WorkingDirectory $EngineRoot
        if ($r.ExitCode -ne 0) {
            $s.Problem = 'o python do venv não executa (código {0}): {1}' -f $r.ExitCode, ((@($r.StdErr -split "\r?\n") | Where-Object { $_ } | Select-Object -First 1))
            return $s
        }
        $s.Version = $r.StdOut.Trim()
        $s.VersionOk = ($s.Version -match '^3\.(1[2-9]|[2-9]\d)\.')

        $r2 = Invoke-Native -File $Py -Arguments @('-I', '-B', '-c', 'import jobos,sys;print(jobos.__version__);print(jobos.__file__)') -WorkingDirectory $EngineRoot
        if ($r2.ExitCode -eq 0) {
            $lines = @($r2.StdOut -split "\r?\n" | Where-Object { $_ })
            $s.ImportOk = ($lines.Count -ge 1)
            if ($lines.Count -ge 1) { $s.JobosVersion = $lines[0].Trim() }
            if ($lines.Count -ge 2) { $s.JobosFile = $lines[1].Trim() }
        }
        else {
            $s.Problem = 'import jobos falhou: ' + ((@($r2.StdErr -split "\r?\n") | Where-Object { $_ } | Select-Object -Last 1))
        }
    }
    catch {
        $s.Problem = $_.Exception.Message
    }
    return $s
}

function Show-Diagnosis {
    # Imprime as seções 1 a 3 e devolve o estado do venv e do Python base.
    param([string]$EngineRoot, [string]$Py)
    Write-Step '[1/3] Python base (py -3.12)'
    $base = Get-BasePython
    if ($base.LauncherPath) { Write-Item 'launcher py' $base.LauncherPath } else { Write-Item 'launcher py' 'NÃO ENCONTRADO' }
    if ($base.Found) {
        Write-Item 'Python 3.12' ('OK {0} ({1}) via {2}' -f $base.Version, $base.RealExe, $base.Origin)
    }
    else {
        Write-Item 'Python 3.12' 'NÃO ENCONTRADO'
    }
    foreach ($n in $base.Notes) { Write-Item 'nota' $n }

    Write-Step '[2/3] Ambiente virtual (.venv)'
    $venv = Get-VenvState -Py $Py -EngineRoot $EngineRoot
    Write-Item 'python do venv' $Py
    if (-not $venv.Exists) {
        Write-Item 'estado' 'AUSENTE'
    }
    else {
        Write-Item 'estado' 'presente'
        if ($venv.Version) { Write-Item 'versão' ('{0} {1}' -f $venv.Version, $(if ($venv.VersionOk) { '(OK, >= 3.12)' } else { '(ANTIGA: o app exige >= 3.12)' })) }
        if ($venv.Problem -and -not $venv.Version) { Write-Item 'problema' $venv.Problem }
    }

    Write-Step '[3/3] Pacote jobos no venv'
    if ($venv.ImportOk) {
        Write-Item 'import jobos' ('OK versão {0}' -f $venv.JobosVersion)
        Write-Item 'arquivo' $venv.JobosFile
        if ($venv.JobosFile -and -not $venv.JobosFile.StartsWith($EngineRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            Write-Item 'AVISO' 'jobos é carregado de fora desta raiz; reinstale com bootstrap.ps1 (pip install -e)'
        }
    }
    elseif ($venv.Exists) {
        Write-Item 'import jobos' 'FALHOU'
        if ($venv.Problem) { Write-Item 'detalhe' $venv.Problem }
    }
    else {
        Write-Item 'import jobos' 'não verificado (sem venv)'
    }
    return [pscustomobject]@{ Base = $base; Venv = $venv }
}

# --------------------------------------------------------------------------- principal

function Invoke-Main {
    $saved = $null
    $pushed = $false
    try {
        try { $engineRoot = Resolve-EngineRoot -Candidate $Root }
        catch {
            Write-Err ('ERRO: ' + $_.Exception.Message)
            $script:ExitCode = 5
            return
        }
        $py = Join-Path $engineRoot '.venv\Scripts\python.exe'
        $venvDir = Join-Path $engineRoot '.venv'

        Write-Host '=== JOBOS bootstrap ==='
        Write-Host ('Raiz  : {0}' -f $engineRoot)
        Write-Host ('Modo  : {0}' -f $(if ($CheckOnly) { 'somente verificação (-CheckOnly), nada será alterado' } else { 'instalação/atualização' }))
        if ($CheckOnly -and $Recreate) { Write-Host 'AVISO : -Recreate ignorado porque -CheckOnly foi informado' }

        $saved = Set-EngineEnv -EngineRoot $engineRoot
        Push-Location -LiteralPath $engineRoot
        $pushed = $true

        $diag = Show-Diagnosis -EngineRoot $engineRoot -Py $py
        $base = $diag.Base
        $venv = $diag.Venv

        # ------------------------------------------------------------- -CheckOnly
        if ($CheckOnly) {
            $ready = ($venv.Exists -and $venv.VersionOk -and $venv.ImportOk)
            Write-Host ''
            if ($ready) {
                Write-Host 'RESULTADO: ambiente pronto. O doctor não foi executado em -CheckOnly (rode: bootstrap.ps1 sem -CheckOnly, ou python -m jobos doctor).'
                $script:ExitCode = 0
            }
            else {
                Write-Host 'RESULTADO: ambiente incompleto. Rode scripts\windows\bootstrap.ps1 (sem -CheckOnly) para preparar.'
                $script:ExitCode = 5
            }
            return
        }

        # ------------------------------------------------------------- criação / recriação do venv
        $needVenv = (-not $venv.Exists) -or $Recreate -or ($venv.Exists -and -not $venv.VersionOk)
        if ($venv.Exists -and -not $venv.VersionOk -and -not $Recreate) {
            Write-Host ''
            Write-Err 'ERRO: o .venv existente usa Python anterior ao 3.12. Rode novamente com -Recreate (o venv antigo será renomeado, não apagado).'
            $script:ExitCode = 5
            return
        }

        if ($needVenv) {
            if (-not $base.Found) {
                Write-Host ''
                Write-Err 'ERRO: Python 3.12 não encontrado (py -3.12). Instale o Python 3.12 e rode novamente.'
                $script:ExitCode = 5
                return
            }

            if ($venv.Exists -and $Recreate) {
                # recusa renomear se houver processo usando o venv (não encerra nada)
                $busy = @()
                try {
                    $busy = @(Get-CimInstance -ClassName Win32_Process -ErrorAction Stop | Where-Object {
                            ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($venvDir + '\', [System.StringComparison]::OrdinalIgnoreCase)) -or
                            ($_.CommandLine -and $_.CommandLine.IndexOf($venvDir + '\', [System.StringComparison]::OrdinalIgnoreCase) -ge 0)
                        })
                }
                catch { $busy = @() }
                if ($busy.Count -gt 0) {
                    Write-Host ''
                    Write-Err 'ERRO: há processos usando o .venv; nada foi alterado. Feche-os e rode novamente:'
                    foreach ($b in $busy) { Write-Err ('       PID {0} {1}' -f $b.ProcessId, $b.Name) }
                    $script:ExitCode = 3
                    return
                }
                $stamp = (Get-Date).ToString('yyyyMMdd-HHmmss', $script:Inv)
                $backupName = ".venv.bak-$stamp"
                Rename-Item -LiteralPath $venvDir -NewName $backupName
                Write-Step ('[+] .venv antigo renomeado para {0} (não foi apagado)' -f $backupName)
            }

            Write-Step '[+] Criando o ambiente virtual (.venv)'
            $venvArgs = @($base.Prefix) + @('-m', 'venv', $venvDir)
            $code = Invoke-Live -File $base.Exe -Arguments $venvArgs -WorkingDirectory $engineRoot
            if ($code -ne 0 -or -not (Test-Path -LiteralPath $py -PathType Leaf)) {
                Write-Err ('ERRO: falha ao criar o venv (código {0}).' -f $code)
                $script:ExitCode = 3
                return
            }
            Write-Host '      venv criado.'
        }
        else {
            Write-Step '[=] .venv já existe e é 3.12 ou superior; será reaproveitado'
        }

        # ------------------------------------------------------------- instalação do pacote
        Write-Step '[+] Instalando dependências e o pacote jobos (pip)'
        $lock = Join-Path $engineRoot 'requirements.lock'
        if (Test-Path -LiteralPath $lock -PathType Leaf) {
            Write-Host '      usando requirements.lock'
            $code = Invoke-Live -File $py -Arguments @('-m', 'pip', 'install', '--disable-pip-version-check', '-r', $lock) -WorkingDirectory $engineRoot
            if ($code -ne 0) { Write-Err ('ERRO: pip install -r requirements.lock falhou (código {0}).' -f $code); $script:ExitCode = 3; return }
            $code = Invoke-Live -File $py -Arguments @('-m', 'pip', 'install', '--disable-pip-version-check', '--no-deps', '-e', $engineRoot) -WorkingDirectory $engineRoot
            if ($code -ne 0) { Write-Err ('ERRO: pip install --no-deps -e falhou (código {0}).' -f $code); $script:ExitCode = 3; return }
        }
        else {
            Write-Host '      sem requirements.lock; usando pip install -e "<raiz>[dev]"'
            $code = Invoke-Live -File $py -Arguments @('-m', 'pip', 'install', '--disable-pip-version-check', '-e', ($engineRoot + '[dev]')) -WorkingDirectory $engineRoot
            if ($code -ne 0) { Write-Err ('ERRO: pip install -e [dev] falhou (código {0}).' -f $code); $script:ExitCode = 3; return }
        }

        $after = Get-VenvState -Py $py -EngineRoot $engineRoot
        if (-not $after.ImportOk) {
            Write-Err ('ERRO: depois da instalação, "import jobos" ainda falha. {0}' -f $after.Problem)
            $script:ExitCode = 3
            return
        }
        Write-Host ('      import jobos OK (versão {0})' -f $after.JobosVersion)

        # ------------------------------------------------------------- doctor
        Write-Step '[+] python -m jobos doctor'
        $doc = Invoke-Native -File $py -Arguments @('-m', 'jobos', 'doctor') -WorkingDirectory $engineRoot
        Write-NativeOutput -Result $doc
        Write-Host ''
        Write-Host ('doctor terminou com código {0}' -f $doc.ExitCode)
        $script:ExitCode = [int]$doc.ExitCode
    }
    catch {
        Write-Err ('ERRO inesperado: {0} (linha {1})' -f $_.Exception.Message, $_.InvocationInfo.ScriptLineNumber)
        $script:ExitCode = 3
    }
    finally {
        if ($pushed) { Pop-Location }
        Restore-EngineEnv -Saved $saved
    }
}

Invoke-Main
exit $script:ExitCode
