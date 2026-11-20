# Freefield on your own NVIDIA GPU, on Windows, with one line in PowerShell:
#
#   irm https://raw.githubusercontent.com/neuregex/freefield/main/start.ps1 | iex
#
# It checks the GPU, its driver and Docker Desktop (and offers to install Docker Desktop), runs the
# ghcr.io/neuregex/freefield image with the models in a Docker volume and opens the studio in the browser while the
# models download. It asks nothing else here: as on RunPod and Vast.ai, the studio shows how the download goes, asks
# for a Hugging Face token when a model needs one (its Models panel) and offers a desktop icon, which this window makes
# (the studio runs in Linux and cannot reach the desktop). Next time: the icon, or the same line. A new image is
# picked up whenever Freefield is not already running. Its messages are in English, like the video and the README.
# From the copy it keeps:  powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\Freefield\start.ps1" stop|logs|uninstall
# Optional: $env:FREEFIELD_PACKS picks the model packs (packs/index.json), $env:HF_TOKEN goes in at the first start,
# $env:FREEFIELD_IMAGE runs another image (a branch's, to try it before it is merged).
# Under the hood these are the same docker commands as in docs/cloud-gpus.md; it runs on Windows PowerShell 5.1 and 7.

& {
param([string]$Self, [object[]]$Rest)

$Action = 'start'
if (@($Rest).Count -gt 0 -and "$(@($Rest)[0])") { $Action = "$(@($Rest)[0])".ToLower() }

$ErrorActionPreference = 'Continue'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch {}

$Ref = 'main'
if ($env:FREEFIELD_LAUNCHER_REF) { $Ref = $env:FREEFIELD_LAUNCHER_REF }   # to try a branch before it is merged
$Raw = "https://raw.githubusercontent.com/neuregex/freefield/$Ref"
$Image = 'ghcr.io/neuregex/freefield:latest'
if ($env:FREEFIELD_IMAGE) { $Image = $env:FREEFIELD_IMAGE }
$Name = 'freefield'                       # the container and the volume, as in docs/cloud-gpus.md
$OnWindows = [Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT
if ($env:LOCALAPPDATA) { $AppDir = Join-Path $env:LOCALAPPDATA 'Freefield' } else { $AppDir = Join-Path $HOME '.freefield' }
$LocalCopy = Join-Path $AppDir 'start.ps1'
$IconFile = Join-Path $AppDir 'freefield.ico'
$Docker = $null
$RamGb = 0

$IconState = '/workspace/freefield/desktop-icon'   # the studio writes "wanted" or "declined" there, this window "created"
$Desk = $null
if ($OnWindows) { $Desk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Freefield.lnk' }

$T = @{
  title = 'Freefield on your own GPU'
  gpu_ok = 'GPU: {0}, {1} GB of VRAM, CUDA {2}'
  gpu_none = 'No NVIDIA GPU found. Freefield needs an NVIDIA card (24 GB for most apps). Without one, use RunPod or Vast.ai in one click: https://github.com/neuregex/freefield#one-click-on-runpod-or-vastai'
  driver_old = 'Your NVIDIA driver goes up to CUDA {0}, and Freefield needs CUDA 13 (driver 580 or newer). Update it from the NVIDIA App or https://www.nvidia.com/drivers and run this again.'
  gpu_old = '{0} is older than what CUDA 13 supports: it needs an RTX 20 series card or newer.'
  vram_low = 'Only {0} GB of VRAM: most apps need 24 GB, so some will not run on this card.'
  docker_missing = 'Docker Desktop is not installed. Freefield runs inside it, so you do not need Python, CUDA or ComfyUI.'
  docker_install_q = 'Install it now with winget?'
  docker_installing = 'Installing Docker Desktop (Windows will ask for permission)...'
  docker_after = 'When it finishes: restart the PC if it asks, open Docker Desktop once and accept its terms, then run this again.'
  docker_manual = 'Download it from https://www.docker.com/products/docker-desktop/ (keep "Use WSL 2" checked), open it once, then run this again.'
  docker_starting = 'Starting Docker Desktop (if it shows its terms, accept them)...'
  docker_timeout = 'Docker Desktop did not start. Open it, wait until it says Engine running, and run this again.'
  docker_windows = 'Docker Desktop is set to Windows containers: right-click its icon next to the clock, choose "Switch to Linux containers", and run this again.'
  docker_ok = 'Docker {0}, {1} GB of RAM for its containers'
  hdd = 'Docker keeps Freefield on {0}, which is a hard disk: models load slowly from it, so the first image can take several minutes. On an SSD it takes seconds: Docker Desktop > Settings > Resources > Advanced > Disk image location.'
  docker_lowram = 'Docker can use only {0} GB of RAM: if Freefield closes while it loads a model, give Docker more: https://github.com/neuregex/freefield#on-your-own-pc-in-one-line'
  pulling = 'Getting the latest Freefield (about 4.5 GB the first time, only the changes after that)...'
  pull_failed = 'Could not check for a new version (no internet?); starting the one you have.'
  pull_none = 'Could not download Freefield. Check your internet connection and run this again.'
  updating = 'There is a new version of Freefield: updating it (your models and history stay)...'
  first_run = 'Downloading the models ({0:N1} GB, only this once). The studio opens in about a minute and shows how it goes.'
  bg_download = 'The models keep downloading in the background: the studio shows how it goes, and each app works as soon as its files are in.'
  starting = 'Starting Freefield...'
  dl = 'Downloading models: {0:N1} of {1:N1} GB'
  loading = 'Starting ComfyUI and the studio'
  models_ok = 'Models ready ({0})'
  ready = 'Freefield is ready: {0}'
  opening = 'Opening it in your browser.'
  already = 'Freefield is already running.'
  gpu_fail = 'Docker could not use the GPU. In Docker Desktop, Settings > General must have "Use the WSL 2 based engine" on; update Docker Desktop and the NVIDIA driver, then run this again.'
  port_busy = 'Port {0} is busy; using {1}.'
  run_fail = 'Freefield did not start:'
  exited = 'Freefield stopped (exit code {0}). The end of its log:'
  oom = 'It ran out of memory. Docker has {0} GB of RAM: create %UserProfile%\.wslconfig with the two lines [wsl2] and memory=40GB, run "wsl --shutdown", open Docker Desktop and run this again.'
  log_saved = 'Its whole log (passcode and token removed) is in {0}: attach it to an issue at https://github.com/neuregex/freefield/issues if you need help.'
  icon_ok = 'Desktop icon created, as you asked in the studio: next time, double-click Freefield on the desktop.'
  stop_hint = 'Press Enter here to stop Freefield and free the GPU, or close this window to leave it running'
  stopping = 'Stopping Freefield...'
  stopped = 'Stopped. The models and the history stay; next time it starts in about a minute.'
  not_installed = 'Freefield is not installed on this computer yet.'
  uninstall_q = 'Remove the Freefield container, its image, the desktop icon and this launcher?'
  uninstall_models_q = 'Also delete the downloaded models and your history (the "freefield" volume)?'
  uninstalled = 'Freefield removed.'
  close = 'Press Enter to close'
  yes = ' [Y/n]'
  no = ' [y/N]'
}

function Msg([string]$Key) {
  $s = $T[$Key]
  if ($args.Count -gt 0) { $s = $s -f $args }
  return $s
}

function Say([string]$Kind, [string]$Text) {
  switch ($Kind) {
    'ok'    { Write-Host "  [ok] $Text" -ForegroundColor Green }
    'warn'  { Write-Host "  [!]  $Text" -ForegroundColor Yellow }
    'bad'   { Write-Host "  [x]  $Text" -ForegroundColor Red }
    'step'  { Write-Host $Text -ForegroundColor Cyan }
    default { Write-Host "       $Text" }
  }
}

function Ask([string]$Question, [bool]$DefaultYes) {
  if ($DefaultYes) { $suffix = Msg 'yes' } else { $suffix = Msg 'no' }
  $a = "$(Read-Host ($Question + $suffix))".Trim().ToLower()
  if (-not $a) { return $DefaultYes }
  return ($a -match '^(y|s)')
}

function Wait-Close {
  if ($Self) { [void](Read-Host (Msg 'close')) }   # a window opened from the desktop icon would close at once
}

function Format-Dur([int]$Sec) {
  if ($Sec -ge 60) { return ('{0} min {1} s' -f [int][math]::Floor($Sec / 60), ($Sec % 60)) }
  return "$Sec s"
}

function Open-Url([string]$Url) {
  try { if ($OnWindows) { Start-Process $Url } else { Start-Process 'xdg-open' -ArgumentList $Url } } catch {}
}

# docker, with stdout and stderr as text lines and the exit code; never throws, on Windows PowerShell 5.1 either
function Dk {
  $old = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try { $o = @(& $Docker @args 2>&1 | ForEach-Object { "$_" }) }
  finally { $ErrorActionPreference = $old }
  $code = $LASTEXITCODE
  return New-Object psobject -Property @{ Code = $code; Out = $o; Text = ($o -join "`n") }
}

function First-Line($Lines, [string]$Pattern) {
  foreach ($l in @($Lines)) { if ("$l" -match $Pattern) { return "$l" } }
  return ''
}

function Test-Gpu {
  $smi = ''
  $c = Get-Command nvidia-smi -ErrorAction SilentlyContinue
  if ($c) { $smi = $c.Source }
  elseif ($OnWindows -and $env:ProgramFiles -and (Test-Path (Join-Path $env:ProgramFiles 'NVIDIA Corporation\NVSMI\nvidia-smi.exe'))) {
    $smi = Join-Path $env:ProgramFiles 'NVIDIA Corporation\NVSMI\nvidia-smi.exe'   # where older drivers put it
  }
  if (-not $smi) { Say 'bad' (Msg 'gpu_none'); return $false }
  $old = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {
    $rows = @(& $smi '--query-gpu=name,memory.total' '--format=csv,noheader,nounits' 2>$null | ForEach-Object { "$_" })
    $caps = @(& $smi '--query-gpu=compute_cap' '--format=csv,noheader,nounits' 2>$null | ForEach-Object { "$_" })
    $head = @(& $smi 2>$null | ForEach-Object { "$_" }) -join "`n"
  } finally { $ErrorActionPreference = $old }
  $inv = [Globalization.CultureInfo]::InvariantCulture
  $best = $null
  for ($i = 0; $i -lt $rows.Count; $i++) {
    $p = $rows[$i] -split ',\s*'
    if ($p.Count -lt 2) { continue }
    $mem = 0.0
    if (-not [double]::TryParse($p[1].Trim(), [Globalization.NumberStyles]::Float, $inv, [ref]$mem)) { continue }
    $cc = 0.0   # 0 when this nvidia-smi does not know compute_cap: then the check is skipped
    if ($i -lt $caps.Count) { [void][double]::TryParse("$($caps[$i])".Trim(), [Globalization.NumberStyles]::Float, $inv, [ref]$cc) }
    if ((-not $best) -or ($mem -gt $best.Mem)) { $best = @{ Name = $p[0].Trim(); Mem = $mem; Cc = $cc } }
  }
  if (-not $best) { Say 'bad' (Msg 'gpu_none'); return $false }
  $cuda = '?'
  $major = 99
  if ($head -match 'CUDA (UMD )?Version:\s*(\d+)\.(\d+)') { $cuda = $Matches[2] + '.' + $Matches[3]; $major = [int]$Matches[2] }
  if ($major -lt 13) { Say 'bad' (Msg 'driver_old' $cuda); return $false }
  if ($best.Cc -gt 0 -and $best.Cc -lt 7.5) { Say 'bad' (Msg 'gpu_old' $best.Name); return $false }
  $gb = [int][math]::Round($best.Mem / 1024)
  Say 'ok' (Msg 'gpu_ok' $best.Name $gb $cuda)
  if ($gb -lt 20) { Say 'warn' (Msg 'vram_low' $gb) }
  return $true
}

function Find-Docker {
  $c = Get-Command docker -ErrorAction SilentlyContinue
  if ($c) { return $c.Source }
  if ($OnWindows -and $env:ProgramFiles) {
    $p = Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe'   # installed, but this window has the old PATH
    if (Test-Path $p) { return $p }
  }
  return $null
}

function Install-Docker {
  Say 'bad' (Msg 'docker_missing')
  if ($OnWindows -and (Get-Command winget -ErrorAction SilentlyContinue)) {
    if (Ask (Msg 'docker_install_q') $true) {
      Say 'step' (Msg 'docker_installing')
      & winget install -e --id Docker.DockerDesktop
      Say 'plain' (Msg 'docker_after')
      return
    }
  }
  Say 'plain' (Msg 'docker_manual')
}

# the engine's "OSType|version|memory" line, starting Docker Desktop and waiting for it when it is closed
function Get-Engine {
  $f = '{{.OSType}}|{{.ServerVersion}}|{{.MemTotal}}'
  $line = First-Line (Dk info --format $f).Out '^\w+\|'
  if ($line) { return $line }
  $exe = ''
  if ($OnWindows -and $env:ProgramFiles) { $exe = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe' }
  if (-not ($exe -and (Test-Path $exe))) { return '' }
  Say 'step' (Msg 'docker_starting')
  Start-Process -FilePath $exe
  $t0 = Get-Date
  while (((Get-Date) - $t0).TotalSeconds -lt 240) {
    Start-Sleep -Seconds 4
    $line = First-Line (Dk info --format $f).Out '^\w+\|'
    if ($line) { return $line }
  }
  return ''
}

# Docker Desktop keeps its disk (images, the models' volume) where its WSL distro lives; WSL lists that in the
# registry. On a hard disk every model loads at ~100 MB/s, which makes the first image take minutes: say so.
function Test-DockerDisk {
  if (-not $OnWindows) { return }
  try {
    $base = ''
    foreach ($k in @(Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss' -ErrorAction SilentlyContinue)) {
      $p = Get-ItemProperty -Path $k.PSPath -ErrorAction SilentlyContinue
      if ("$($p.DistributionName)" -eq 'docker-desktop-data') { $base = "$($p.BasePath)"; break }   # older Docker Desktop
      if ("$($p.DistributionName)" -eq 'docker-desktop') { $base = "$($p.BasePath)" }
    }
    $base = $base -replace '^\\\\\?\\', ''
    if ($base -notmatch '^([A-Za-z]):') { return }
    $letter = $Matches[1]
    $num = (Get-Partition -DriveLetter $letter -ErrorAction Stop).DiskNumber
    $disk = @(Get-PhysicalDisk -ErrorAction Stop | Where-Object { "$($_.DeviceId)" -eq "$num" })[0]
    if ($disk -and "$($disk.MediaType)" -eq 'HDD') { Say 'warn' (Msg 'hdd' ($letter.ToUpper() + ':')) }
  } catch {}
}

# what Freefield's container looks like now, or $null: status, image, the env it was made with, and its port.
# "container inspect": a bare "docker inspect freefield" also finds the volume of that name once the container is gone
function Get-Box {
  $r = Dk container inspect $Name --format '{{json .}}'
  if ($r.Code -ne 0) { return $null }
  $json = First-Line $r.Out '^\{'
  if (-not $json) { return $null }
  try { $j = $json | ConvertFrom-Json } catch { return $null }
  $envs = [ordered]@{}
  foreach ($e in @($j.Config.Env)) {
    $s = "$e"
    $i = $s.IndexOf('=')
    if ($i -le 0) { continue }
    $k = $s.Substring(0, $i)
    if ($k -eq 'HF_TOKEN' -or $k -like 'FREEFIELD_*') { $envs[$k] = $s.Substring($i + 1) }
  }
  $port = 3000
  $bind = '127.0.0.1'
  $pb = $null
  try { $pb = @($j.HostConfig.PortBindings.'3000/tcp')[0] } catch {}
  if ($pb) {
    if ("$($pb.HostPort)") { $port = [int]"$($pb.HostPort)" }
    $bind = "$($pb.HostIp)"
  }
  return New-Object psobject -Property @{ Status = "$($j.State.Status)"; ImageId = "$($j.Image)"; Env = $envs; Port = $port; Bind = $bind }
}

function Test-PortFree([int]$Port) {
  if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { return $false }
  }
  try {
    $l = New-Object Net.Sockets.TcpListener -ArgumentList ([Net.IPAddress]::Loopback), $Port
    $l.Start()
    $l.Stop()
    return $true
  } catch { return $false }
}

function Find-Port {
  for ($p = 3000; $p -le 3020; $p++) {
    if (Test-PortFree $p) {
      if ($p -ne 3000) { Say 'warn' (Msg 'port_busy' 3000 $p) }
      return $p
    }
  }
  return 3000
}

# docker run, with HF_TOKEN and FREEFIELD_* passed through this process's environment (never on the command line)
function New-Box($Envs, [int]$Port, [string]$Bind) {
  if ($Bind -and $Bind -ne '0.0.0.0') { $map = "${Bind}:${Port}:3000" } else { $map = "${Port}:3000" }
  $dargs = @('run', '-d', '--name', $Name, '--gpus', 'all', '-p', $map, '-v', "${Name}:/workspace")
  $saved = @{}
  foreach ($k in @($Envs.Keys)) {
    $v = "$($Envs[$k])"
    if (-not $v) { continue }
    $saved[$k] = [Environment]::GetEnvironmentVariable($k)
    [Environment]::SetEnvironmentVariable($k, $v)
    $dargs += @('-e', $k)
  }
  try { return (Dk @dargs $Image) }
  finally { foreach ($k in @($saved.Keys)) { [Environment]::SetEnvironmentVariable($k, $saved[$k]) } }
}

function Show-RunError($R) {
  Say 'bad' (Msg 'run_fail')
  foreach ($l in @($R.Out | Select-Object -Last 8)) { Write-Host "    $l" -ForegroundColor DarkGray }
  if ($R.Text -match 'gpu|nvidia|device driver') { Say 'warn' (Msg 'gpu_fail') }
}

function Save-Log {
  try {
    New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
    $f = Join-Path $AppDir 'freefield-log.txt'
    $lines = @((Dk logs $Name).Out | ForEach-Object {
      $_ -replace '(\?key=)\S+', '$1<passcode>' -replace '(Passcode:\s+)\S+', '$1<passcode>' -replace '(FREEFIELD_TOKEN=)\S+', '$1<token>'
    })
    [IO.File]::WriteAllLines($f, [string[]]$lines, (New-Object Text.UTF8Encoding -ArgumentList $false))
    Say 'plain' (Msg 'log_saved' $f)
  } catch {}
}

# follows the log from $Since: download progress, errors, then the banner's passcode (Key, '' if Freefield stopped)
# and whether the models keep downloading after it (Downloading: the studio shows that part).
# With $Attach (Freefield was already running) what the log said before is not told again, only what comes next.
function Wait-Ready([string]$Since, [bool]$Attach) {
  $down = [string][char]0x2193
  $cross = [string][char]0x2717
  $seen = 0
  $need = 0.0
  $done = 0.0
  $got = 0.0
  $key = ''
  $ready = $false
  $bg = $false
  $hint = $false
  $quiet = $Attach
  $t0 = Get-Date
  $lastDu = $t0.AddMinutes(-1)
  while ($true) {
    $lg = Dk logs --since $Since $Name
    $lines = @($lg.Out)
    for ($i = $seen; $i -lt $lines.Count; $i++) {
      $l = $lines[$i]
      if ($l -match '^packs .*?(\d+) to download \(([\d.]+) GB\)') {
        if ([int]$Matches[1] -gt 0) {
          $need = [double]$Matches[2]
          if (-not $quiet) { Say 'step' (Msg 'first_run' $need) }
        }
        $hint = $false
      } elseif ($l -match ('^\s+' + $down + '\s+(\S+)\s+([\d.]+) GB')) {
        $done += [double]$Matches[2]
        if (-not $quiet) { Say 'ok' ($Matches[1] + '  ' + $Matches[2] + ' GB') }
        $hint = $false
      } elseif ($l -match ('^\s+' + $cross + '\s+(.+)$')) {
        Say 'bad' $Matches[1]
        $hint = $true
      } elseif ($hint -and $l -match '^\s{4}\S') {
        Say 'plain' ('  ' + $l.Trim())
      } elseif ($l -match '^models ready in (\d+) s') {
        $need = 0.0
        if (-not $quiet) { Say 'ok' (Msg 'models_ok' (Format-Dur ([int]$Matches[1]))) }
        $hint = $false
      } elseif ($l -match '^! (.+)$') {
        $msg = $Matches[1]
        $studio = $msg -like "*Models panel*"   # the studio shows it, with the button that fixes it
        if (-not $quiet -and -not $studio) { Say 'warn' $msg }
        if ($msg -like '*could not be downloaded*') { $need = 0.0 }
        $hint = -not ($quiet -or $studio)   # the links under it
      } elseif ($l -match 'The models are still downloading') {
        $bg = $true
      } elseif ($l -match '^Freefield is ready on') {
        $ready = $true
      } elseif ($l -match '\?key=(\S+)') {
        $key = $Matches[1]
      } else {
        $hint = $false
      }
    }
    $seen = $lines.Count
    $quiet = $false
    if ($ready -and $key) { break }

    $st = First-Line (Dk container inspect $Name --format '{{.State.Status}}|{{.State.ExitCode}}|{{.State.OOMKilled}}').Out '^\w+\|'
    if ($st -and -not $st.StartsWith('running')) {
      Write-Progress -Activity 'Freefield' -Completed
      $p = $st.Split('|')
      Say 'bad' (Msg 'exited' $p[1])
      foreach ($t in @($lines | Select-Object -Last 25)) { Write-Host "    $t" -ForegroundColor DarkGray }
      if ($p[1] -eq '137' -or $p[2] -eq 'true') { Say 'warn' (Msg 'oom' $RamGb) }
      Save-Log
      return @{ Key = ''; Downloading = $false }
    }
    $elapsed = Format-Dur ([int]((Get-Date) - $t0).TotalSeconds)
    if ($need -gt 0) {
      if (((Get-Date) - $lastDu).TotalSeconds -ge 5) {
        $lastDu = Get-Date
        $part = 0.0
        $du = First-Line (Dk exec $Name du -sb /workspace/freefield/models/.incoming).Out '^\d+'
        if ($du -match '^(\d+)') { $part = [double]$Matches[1] / 1e9 }
        $got = [math]::Min($need, $done + $part)
      }
      $pct = [int][math]::Min(99, [math]::Floor(100 * $got / $need))
      Write-Progress -Activity 'Freefield' -Status ((Msg 'dl' $got $need) + '  -  ' + $elapsed) -PercentComplete $pct
    } else {
      Write-Progress -Activity 'Freefield' -Status ((Msg 'loading') + '  -  ' + $elapsed)
    }
    Start-Sleep -Seconds 2
  }
  Write-Progress -Activity 'Freefield' -Completed
  return @{ Key = $key; Downloading = ($bg -and -not $Attach) }
}

# keeps a copy of this launcher (UTF-8 with BOM, which Windows PowerShell 5.1 needs for the accents) and the icon
function Save-Copy {
  try {
    New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
    $src = Invoke-RestMethod -Uri "$Raw/start.ps1" -TimeoutSec 20 -UseBasicParsing
    if ($src -is [string] -and $src.Contains('neuregex/freefield')) {
      $src = $src.TrimStart([char]0xFEFF)
      $same = $false
      if (Test-Path $LocalCopy) { $same = ([IO.File]::ReadAllText($LocalCopy).TrimStart([char]0xFEFF) -eq $src) }
      if (-not $same) { [IO.File]::WriteAllText($LocalCopy, $src, (New-Object Text.UTF8Encoding -ArgumentList $true)) }
    }
    if (-not (Test-Path $IconFile)) {
      Invoke-WebRequest -Uri "$Raw/docs/media/freefield.ico" -OutFile $IconFile -UseBasicParsing -TimeoutSec 20
    }
  } catch {}
}

function New-Icon {
  try {
    $lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Freefield.lnk'
    $ws = New-Object -ComObject WScript.Shell
    $sc = $ws.CreateShortcut($lnk)
    $sc.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $sc.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $LocalCopy + '"'
    $sc.WorkingDirectory = $AppDir
    if (Test-Path $IconFile) { $sc.IconLocation = $IconFile + ',0' }
    $sc.Description = 'Freefield'
    $sc.Save()
    return $true
  } catch { return $false }
}

# The desktop icon the studio offered (FREEFIELD_DESKTOP_ICON=1): the studio keeps the answer in the volume, and this
# window, on Windows, makes the icon and answers "created". 'made' when it made it just now, else the state.
function Sync-Icon {
  $state = First-Line (Dk exec $Name cat $IconState).Out '^(wanted|created|declined)$'
  if (-not $state -and $Desk -and (Test-Path $Desk)) {   # an icon from an earlier start: the studio need not ask
    [void](Dk exec $Name sh -c "printf created > $IconState")
    return 'created'
  }
  if ($state -ne 'wanted') { return $state }
  if (-not (Test-Path $LocalCopy)) { Save-Copy }
  if ((Test-Path $LocalCopy) -and (New-Icon)) {
    [void](Dk exec $Name sh -c "printf created > $IconState")
    Write-Host ''
    Say 'ok' (Msg 'icon_ok')
    return 'made'
  }
  return ''   # try again at the next look
}

# Enter stops Freefield; meanwhile the icon is made as soon as the studio asks for it
function Wait-Enter {
  $prompt = (Msg 'stop_hint') + ': '
  Write-Host ''
  Write-Host $prompt -NoNewline
  try { [void][Console]::KeyAvailable } catch { [void](Read-Host); return }   # no console to watch (ISE): just wait
  $watch = [bool]$OnWindows
  $next = Get-Date
  while ($true) {
    while ([Console]::KeyAvailable) {
      if ([Console]::ReadKey($true).Key -eq 'Enter') { Write-Host ''; return }
    }
    if ($watch -and (Get-Date) -ge $next) {
      $s = Sync-Icon
      if ($s -eq 'made') { Write-Host $prompt -NoNewline }
      if ($s -eq 'made' -or $s -eq 'created' -or $s -eq 'declined') { $watch = $false }
      $next = (Get-Date).AddSeconds(3)
    }
    Start-Sleep -Milliseconds 200
  }
}

$prevEnc = $null
try { $prevEnc = [Console]::OutputEncoding; [Console]::OutputEncoding = New-Object Text.UTF8Encoding -ArgumentList $false } catch {}
$prevHints = $env:DOCKER_CLI_HINTS
$env:DOCKER_CLI_HINTS = 'false'   # no "What's next: docker scout ..." after the pull
try { $Host.UI.RawUI.WindowTitle = 'Freefield' } catch {}

try {
  Write-Host ''
  Say 'step' (Msg 'title')

  if ($Action -eq 'start') {
    if (-not (Test-Gpu)) { Wait-Close; return }
  }

  $Docker = Find-Docker
  if (-not $Docker) { Install-Docker; Wait-Close; return }
  $engine = Get-Engine
  if (-not $engine) { Say 'bad' (Msg 'docker_timeout'); Wait-Close; return }
  $ep = $engine.Split('|')
  if ($ep[0] -ne 'linux') { Say 'bad' (Msg 'docker_windows'); Wait-Close; return }
  $mem = 0.0
  [void][double]::TryParse($ep[2], [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref]$mem)
  $RamGb = [math]::Round($mem / 1073741824, 1)
  Say 'ok' (Msg 'docker_ok' $ep[1] $RamGb)
  if ($RamGb -gt 0 -and $RamGb -lt 16) { Say 'warn' (Msg 'docker_lowram' $RamGb) }
  if ($Action -eq 'start') { Test-DockerDisk }

  $box = Get-Box

  if ($Action -eq 'stop') {
    if ($box) { Say 'step' (Msg 'stopping'); [void](Dk stop -t 30 $Name); Say 'ok' (Msg 'stopped') } else { Say 'warn' (Msg 'not_installed') }
    return
  }
  if ($Action -eq 'logs') {
    if ($box) { & $Docker logs --tail 300 $Name } else { Say 'warn' (Msg 'not_installed') }
    return
  }
  if ($Action -eq 'uninstall') {
    if (-not (Ask (Msg 'uninstall_q') $false)) { return }
    [void](Dk rm -f $Name)
    if (Ask (Msg 'uninstall_models_q') $false) { [void](Dk volume rm $Name) }
    [void](Dk image rm $Image)
    if ($OnWindows) { Remove-Item (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Freefield.lnk') -ErrorAction SilentlyContinue }
    Remove-Item $AppDir -Recurse -Force -ErrorAction SilentlyContinue
    Say 'ok' (Msg 'uninstalled')
    return
  }

  $attach = [bool]($box -and $box.Status -eq 'running')
  if ($attach) {
    Say 'ok' (Msg 'already')
  } else {
    # nothing to ask: the image decides the packs unless FREEFIELD_PACKS says otherwise, and the studio asks for a
    # Hugging Face token when a model needs one (Models panel), as on RunPod and Vast.ai
    $envs = [ordered]@{}
    $recreate = $false
    if ($box) {
      $envs = $box.Env
    } elseif ("$env:HF_TOKEN".Trim()) {
      $envs['HF_TOKEN'] = "$env:HF_TOKEN".Trim()
    }
    if ($env:FREEFIELD_PACKS -and $env:FREEFIELD_PACKS -ne $envs['FREEFIELD_PACKS']) {
      $envs['FREEFIELD_PACKS'] = $env:FREEFIELD_PACKS
      $recreate = $true
    }
    if ($OnWindows -and -not $envs['FREEFIELD_DESKTOP_ICON']) {   # the studio offers the desktop icon; this window makes it
      $envs['FREEFIELD_DESKTOP_ICON'] = '1'
      $recreate = $true
    }

    Write-Host ''
    Say 'step' (Msg 'pulling')
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $Docker pull $Image } finally { $ErrorActionPreference = $old }
    $pulled = ($LASTEXITCODE -eq 0)
    $imageId = First-Line (Dk image inspect $Image --format '{{.Id}}').Out '^sha256:'
    if (-not $imageId) { Say 'bad' (Msg 'pull_none'); Wait-Close; return }
    if (-not $pulled) { Say 'warn' (Msg 'pull_failed') }

    if ($box -and $box.ImageId -ne $imageId) { Say 'step' (Msg 'updating') } else { Say 'step' (Msg 'starting') }
    if ($box) {
      if ($box.ImageId -ne $imageId) { $recreate = $true }
      if ($recreate) {
        [void](Dk rm -f $Name)
        $r = New-Box $envs $box.Port $box.Bind
        if ($r.Code -ne 0) { Show-RunError $r; Wait-Close; return }
        if ($box.ImageId -ne $imageId) { [void](Dk image rm $box.ImageId) }   # the old version; kept if anything else uses it
      } else {
        $r = Dk start $Name
        if ($r.Code -ne 0) { Show-RunError $r; Wait-Close; return }
      }
    } else {
      $r = New-Box $envs (Find-Port) '127.0.0.1'
      if ($r.Code -ne 0) { Show-RunError $r; Wait-Close; return }
    }
    $box = Get-Box
  }

  $started = First-Line (Dk container inspect $Name --format '{{.State.StartedAt}}').Out '^\d{4}-'
  $since = $started
  if ($started.Length -ge 19) { $since = $started.Substring(0, 19) + 'Z' }
  $w = Wait-Ready $since $attach
  $key = $w.Key
  if (-not $key) { Wait-Close; return }

  $url = 'http://127.0.0.1:' + $box.Port
  Write-Host ''
  Say 'ok' (Msg 'ready' ($url + '/?key=' + $key))
  Say 'plain' (Msg 'opening')
  Open-Url ($url + '/?key=' + $key)
  if ($w.Downloading) { Say 'plain' (Msg 'bg_download') }

  Save-Copy
  Wait-Enter
  Say 'step' (Msg 'stopping')
  [void](Dk stop -t 30 $Name)
  Say 'ok' (Msg 'stopped')
  Start-Sleep -Seconds 2
}
finally {
  Write-Progress -Activity 'Freefield' -Completed
  if ($prevEnc) { try { [Console]::OutputEncoding = $prevEnc } catch {} }
  $env:DOCKER_CLI_HINTS = $prevHints
}
} $PSCommandPath @($args)
