# Freefield on your own NVIDIA GPU, on Windows, with one line in PowerShell:
#
#   irm https://raw.githubusercontent.com/neuregex/freefield/main/start.ps1 | iex
#
# It checks the GPU, its driver and Docker Desktop (and offers to install Docker Desktop), asks for a Hugging Face
# token the first time and checks it against the FLUX 3 Klein license, runs the ghcr.io/neuregex/freefield image with
# the models in a Docker volume, shows the download, opens the studio in the browser and offers a desktop icon.
# Next time: the icon, or the same line. A new image is picked up whenever Freefield is not already running.
# From the copy it keeps:  powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\Freefield\start.ps1" stop|logs|uninstall
# Optional: $env:FREEFIELD_PACKS picks the model packs (packs/index.json), $env:HF_TOKEN skips the token question.
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
$Name = 'freefield'                       # the container and the volume, as in docs/cloud-gpus.md
$LicenseRepo = 'black-forest-labs/flux-3-image-klein-comfy'
$LicenseFile = 'vae/flux2-vae.safetensors'
$OnWindows = [Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT
if ($env:LOCALAPPDATA) { $AppDir = Join-Path $env:LOCALAPPDATA 'Freefield' } else { $AppDir = Join-Path $HOME '.freefield' }
$LocalCopy = Join-Path $AppDir 'start.ps1'
$IconFile = Join-Path $AppDir 'freefield.ico'
$Docker = $null
$RamGb = 0

$Lang = 'en'
try { if ((Get-UICulture).TwoLetterISOLanguageName -eq 'es' -or (Get-Culture).TwoLetterISOLanguageName -eq 'es') { $Lang = 'es' } } catch {}
if ($env:FREEFIELD_LANG) { $Lang = $env:FREEFIELD_LANG }

$T = @{
en = @{
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
  docker_lowram = 'Docker can use only {0} GB of RAM: if Freefield closes while it loads a model, give Docker more: https://github.com/neuregex/freefield#on-your-own-pc-in-one-line'
  token_have = 'Hugging Face token from HF_TOKEN: it works'
  token_intro1 = 'Most image apps use FLUX 3 Klein. It is free, but Hugging Face asks you to accept its license first:'
  token_intro2 = '  1. On the first page, sign in (or sign up) and accept the license.'
  token_intro3 = '  2. On the second, create a token of type Read and copy it.'
  token_open = 'Press Enter to open both pages'
  token_prompt = 'Paste the token (it will not show) and press Enter, or just press Enter to go on without it'
  token_shape = 'That does not look like a token: it starts with hf_ and is about 37 characters long. Copy it again.'
  token_invalid = 'Hugging Face did not accept that token. Copy it again from https://huggingface.co/settings/tokens'
  token_nolicense = 'The token works (account {0}), but that account has not accepted the FLUX 3 Klein license yet, or the token is not of type Read. I opened the license page again: accept it and press Enter.'
  token_ok = 'The token works and the license is accepted (account {0})'
  token_unknown = 'Could not reach Hugging Face to check the token; going on with it.'
  token_skip = 'Going on without a token: Z-Image and the upscale apps (9 apps instead of 64). Run this again to add it later.'
  token_add_q = 'This Freefield has no Hugging Face token, so FLUX 3 Klein is missing (9 apps instead of 64). Add the token now?'
  pulling = 'Getting the latest Freefield (about 4.5 GB the first time, only the changes after that)...'
  pull_failed = 'Could not check for a new version (no internet?); starting the one you have.'
  pull_none = 'Could not download Freefield. Check your internet connection and run this again.'
  updating = 'There is a new version of Freefield: updating it (your models and history stay)...'
  first_run = 'Downloading the models ({0:N1} GB, only this once; the bar shows how it goes)...'
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
  icon_q = 'Put a Freefield icon on the desktop, to start it with a double click?'
  icon_ok = 'Icon created: next time, double-click Freefield on the desktop.'
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
es = @{
  title = 'Freefield en tu propia GPU'
  gpu_ok = 'GPU: {0}, {1} GB de VRAM, CUDA {2}'
  gpu_none = 'No encontré una GPU NVIDIA. Freefield necesita una tarjeta NVIDIA (de 24 GB para la mayoría de las apps). Si no tienes una, usa RunPod o Vast.ai en un clic: https://github.com/neuregex/freefield#one-click-on-runpod-or-vastai'
  driver_old = 'Tu driver de NVIDIA llega hasta CUDA {0}, y Freefield necesita CUDA 13 (driver 580 o más nuevo). Actualízalo desde la NVIDIA App o https://www.nvidia.com/drivers y vuelve a correr esto.'
  gpu_old = '{0} es más vieja de lo que soporta CUDA 13: necesitas una RTX serie 20 o más nueva.'
  vram_low = 'Solo {0} GB de VRAM: la mayoría de las apps necesita 24 GB, así que algunas no van a correr en esta tarjeta.'
  docker_missing = 'Docker Desktop no está instalado. Freefield corre dentro de él, así no tienes que instalar Python, CUDA ni ComfyUI.'
  docker_install_q = '¿Lo instalo ahora con winget?'
  docker_installing = 'Instalando Docker Desktop (Windows te va a pedir permiso)...'
  docker_after = 'Cuando termine: reinicia la PC si te lo pide, abre Docker Desktop una vez y acepta sus términos, y vuelve a correr esto.'
  docker_manual = 'Descárgalo de https://www.docker.com/products/docker-desktop/ (deja marcado "Use WSL 2"), ábrelo una vez y vuelve a correr esto.'
  docker_starting = 'Abriendo Docker Desktop (si te muestra sus términos, acéptalos)...'
  docker_timeout = 'Docker Desktop no arrancó. Ábrelo, espera a que diga Engine running y vuelve a correr esto.'
  docker_windows = 'Docker Desktop está en modo Windows containers: dale clic derecho a su ícono junto al reloj, elige "Switch to Linux containers" y vuelve a correr esto.'
  docker_ok = 'Docker {0}, {1} GB de RAM para sus contenedores'
  docker_lowram = 'Docker solo puede usar {0} GB de RAM: si Freefield se cierra al cargar un modelo, dale más: https://github.com/neuregex/freefield#on-your-own-pc-in-one-line'
  token_have = 'Token de Hugging Face tomado de HF_TOKEN: funciona'
  token_intro1 = 'La mayoría de las apps de imagen usan FLUX 3 Klein. Es gratis, pero Hugging Face pide aceptar su licencia primero:'
  token_intro2 = '  1. En la primera página, inicia sesión (o regístrate) y acepta la licencia.'
  token_intro3 = '  2. En la segunda, crea un token de tipo Read y cópialo.'
  token_open = 'Presiona Enter para abrir las dos páginas'
  token_prompt = 'Pega el token (no se va a ver) y presiona Enter, o solo Enter para seguir sin él'
  token_shape = 'Eso no parece un token: empieza con hf_ y tiene unos 37 caracteres. Cópialo otra vez.'
  token_invalid = 'Hugging Face no aceptó ese token. Cópialo otra vez de https://huggingface.co/settings/tokens'
  token_nolicense = 'El token funciona (cuenta {0}), pero esa cuenta todavía no acepta la licencia de FLUX 3 Klein, o el token no es de tipo Read. Te abrí la página de la licencia otra vez: acéptala y presiona Enter.'
  token_ok = 'El token funciona y la licencia está aceptada (cuenta {0})'
  token_unknown = 'No pude conectar con Hugging Face para revisar el token; sigo con él.'
  token_skip = 'Sigo sin token: Z-Image y las apps de mejorar imagen (9 apps en vez de 64). Vuelve a correr esto para agregarlo después.'
  token_add_q = 'Este Freefield no tiene token de Hugging Face, así que le falta FLUX 3 Klein (9 apps en vez de 64). ¿Agregar el token ahora?'
  pulling = 'Bajando la versión más nueva de Freefield (unos 4.5 GB la primera vez, después solo lo que cambió)...'
  pull_failed = 'No pude buscar una versión nueva (¿sin internet?); arranco la que tienes.'
  pull_none = 'No pude descargar Freefield. Revisa tu conexión a internet y vuelve a correr esto.'
  updating = 'Hay una versión nueva de Freefield: actualizándolo (tus modelos y tu historial se quedan)...'
  first_run = 'Descargando los modelos ({0:N1} GB, solo esta vez; la barra muestra cómo va)...'
  starting = 'Arrancando Freefield...'
  dl = 'Descargando modelos: {0:N1} de {1:N1} GB'
  loading = 'Arrancando ComfyUI y el estudio'
  models_ok = 'Modelos listos ({0})'
  ready = 'Freefield está listo: {0}'
  opening = 'Lo abro en tu navegador.'
  already = 'Freefield ya está corriendo.'
  gpu_fail = 'Docker no pudo usar la GPU. En Docker Desktop, Settings > General debe tener activado "Use the WSL 2 based engine"; actualiza Docker Desktop y el driver de NVIDIA, y vuelve a correr esto.'
  port_busy = 'El puerto {0} está ocupado; uso el {1}.'
  run_fail = 'Freefield no arrancó:'
  exited = 'Freefield se detuvo (código {0}). El final de su log:'
  oom = 'Se quedó sin memoria. Docker tiene {0} GB de RAM: crea %UserProfile%\.wslconfig con las dos líneas [wsl2] y memory=40GB, corre "wsl --shutdown", abre Docker Desktop y vuelve a correr esto.'
  log_saved = 'El log completo (sin passcode ni token) quedó en {0}: adjúntalo en un issue en https://github.com/neuregex/freefield/issues si necesitas ayuda.'
  icon_q = '¿Pongo un ícono de Freefield en el escritorio, para abrirlo con doble clic?'
  icon_ok = 'Ícono creado: la próxima vez, doble clic en Freefield en el escritorio.'
  stop_hint = 'Presiona Enter aquí para apagar Freefield y liberar la GPU, o cierra esta ventana para dejarlo corriendo'
  stopping = 'Apagando Freefield...'
  stopped = 'Apagado. Los modelos y el historial se quedan; la próxima vez arranca en más o menos un minuto.'
  not_installed = 'Freefield todavía no está instalado en esta computadora.'
  uninstall_q = '¿Quito el contenedor de Freefield, su imagen, el ícono del escritorio y este lanzador?'
  uninstall_models_q = '¿También borro los modelos descargados y tu historial (el volumen "freefield")?'
  uninstalled = 'Freefield quitado.'
  close = 'Presiona Enter para cerrar'
  yes = ' [S/n]'
  no = ' [s/N]'
}
}
if (-not $T.ContainsKey($Lang)) { $Lang = 'en' }

function Msg([string]$Key) {
  $s = $T[$Lang][$Key]
  if (-not $s) { $s = $T['en'][$Key] }
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

function Read-Secret([string]$Prompt) {
  $sec = Read-Host -Prompt $Prompt -AsSecureString
  $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
  try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
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

# what Freefield's container looks like now, or $null: status, image, the env it was made with, and its port
function Get-Box {
  $r = Dk inspect $Name --format '{{json .}}'
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

function Add-Pack($Packs, [string]$Pack) {
  if (-not "$Packs") { return $null }   # the image's default packs already have it
  $list = @("$Packs" -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
  if ($list -notcontains $Pack) { $list += $Pack }
  return ($list -join ',')
}

function Get-Http([string]$Url, [string]$Method, [string]$Token) {
  try {
    $req = [Net.WebRequest]::Create($Url)
    $req.Method = $Method
    $req.AllowAutoRedirect = $false
    $req.Timeout = 20000
    $req.UserAgent = 'freefield-launcher'
    if ($Token) { $req.Headers.Add('Authorization', "Bearer $Token") }
    $res = $req.GetResponse()
    $code = [int]$res.StatusCode
    $body = ''
    if ($Method -eq 'GET') {
      $sr = New-Object IO.StreamReader -ArgumentList $res.GetResponseStream()
      $body = $sr.ReadToEnd()
      $sr.Close()
    }
    $res.Close()
    return @{ Code = $code; Body = $body }
  } catch {
    $ex = $_.Exception
    while ($ex -and -not ($ex -is [Net.WebException])) { $ex = $ex.InnerException }
    if ($ex -and $ex.Response) {
      $code = [int]$ex.Response.StatusCode
      $ex.Response.Close()
      return @{ Code = $code; Body = '' }
    }
    return @{ Code = 0; Body = '' }
  }
}

# 'ok', 'invalid', 'nolicense' or 'unknown' (no answer from Hugging Face), and the account name
function Test-HfToken([string]$Tok) {
  $who = Get-Http 'https://huggingface.co/api/whoami-v2' 'GET' $Tok
  if ($who.Code -eq 401) { return @{ Kind = 'invalid'; User = '' } }
  if ($who.Code -ne 200) { return @{ Kind = 'unknown'; User = '' } }
  $user = '?'
  try { $user = "$(($who.Body | ConvertFrom-Json).name)" } catch {}
  $f = Get-Http "https://huggingface.co/$LicenseRepo/resolve/main/$LicenseFile" 'HEAD' $Tok
  if ($f.Code -eq 403) { return @{ Kind = 'nolicense'; User = $user } }
  if ($f.Code -eq 401) { return @{ Kind = 'invalid'; User = $user } }
  if ($f.Code -ge 200 -and $f.Code -lt 400) { return @{ Kind = 'ok'; User = $user } }
  return @{ Kind = 'unknown'; User = $user }
}

# a Hugging Face token whose account has accepted the FLUX 3 Klein license, or '' to go on without one
function Get-Token {
  $tok = "$env:HF_TOKEN".Trim()
  if ($tok) {
    $r = Test-HfToken $tok
    if ($r.Kind -eq 'ok') { Say 'ok' (Msg 'token_have'); return $tok }
  }
  Write-Host ''
  Say 'plain' (Msg 'token_intro1')
  Say 'plain' (Msg 'token_intro2')
  Say 'plain' (Msg 'token_intro3')
  [void](Read-Host (Msg 'token_open'))
  Open-Url "https://huggingface.co/$LicenseRepo"
  Start-Sleep -Seconds 2
  Open-Url 'https://huggingface.co/settings/tokens'
  for ($try = 0; $try -lt 6; $try++) {
    $tok = "$(Read-Secret (Msg 'token_prompt'))".Trim()
    if (-not $tok) { Say 'warn' (Msg 'token_skip'); return '' }
    if (-not ($tok.StartsWith('hf_') -and $tok.Length -ge 30)) { Say 'warn' (Msg 'token_shape'); continue }
    $r = Test-HfToken $tok
    for ($wait = 0; $r.Kind -eq 'nolicense' -and $wait -lt 4; $wait++) {
      Say 'warn' (Msg 'token_nolicense' $r.User)
      Open-Url "https://huggingface.co/$LicenseRepo"
      [void](Read-Host)
      $r = Test-HfToken $tok
    }
    if ($r.Kind -eq 'ok') { Say 'ok' (Msg 'token_ok' $r.User); return $tok }
    if ($r.Kind -eq 'unknown') { Say 'warn' (Msg 'token_unknown'); return $tok }
    Say 'warn' (Msg 'token_invalid')
  }
  Say 'warn' (Msg 'token_skip')
  return ''
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

# follows the log from $Since: download progress, errors, then the banner's passcode; '' if Freefield stopped.
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
        Say 'plain' $l.Trim()
      } elseif ($l -match '^models ready in (\d+) s') {
        $need = 0.0
        if (-not $quiet) { Say 'ok' (Msg 'models_ok' (Format-Dur ([int]$Matches[1]))) }
        $hint = $false
      } elseif ($l -match '^! (.+)$') {
        $msg = $Matches[1]
        Say 'warn' $msg
        if ($msg -like '*could not be downloaded*') { $need = 0.0 }
        $hint = $false
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

    $st = First-Line (Dk inspect $Name --format '{{.State.Status}}|{{.State.ExitCode}}|{{.State.OOMKilled}}').Out '^\w+\|'
    if ($st -and -not $st.StartsWith('running')) {
      Write-Progress -Activity 'Freefield' -Completed
      $p = $st.Split('|')
      Say 'bad' (Msg 'exited' $p[1])
      foreach ($t in @($lines | Select-Object -Last 25)) { Write-Host "    $t" -ForegroundColor DarkGray }
      if ($p[1] -eq '137' -or $p[2] -eq 'true') { Say 'warn' (Msg 'oom' $RamGb) }
      Save-Log
      return ''
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
  return $key
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

$prevEnc = $null
try { $prevEnc = [Console]::OutputEncoding; [Console]::OutputEncoding = New-Object Text.UTF8Encoding -ArgumentList $false } catch {}
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
    # the questions come before the long download, so whoever runs this can walk away after answering them
    $envs = [ordered]@{}
    $recreate = $false
    if ($box) {
      $envs = $box.Env
      if (-not $envs['HF_TOKEN'] -and (Ask (Msg 'token_add_q') $false)) {
        $tok = Get-Token
        if ($tok) {
          $envs['HF_TOKEN'] = $tok
          $envs['FREEFIELD_PACKS'] = Add-Pack $envs['FREEFIELD_PACKS'] 'image-flux3'
          $recreate = $true
        }
      }
    } else {
      $tok = Get-Token
      if ($tok) { $envs['HF_TOKEN'] = $tok; $envs['FREEFIELD_PACKS'] = 'image-flux3,upscale' } else { $envs['FREEFIELD_PACKS'] = 'image,upscale' }
    }
    if ($env:FREEFIELD_PACKS -and $env:FREEFIELD_PACKS -ne $envs['FREEFIELD_PACKS']) {
      $envs['FREEFIELD_PACKS'] = $env:FREEFIELD_PACKS
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

    Say 'step' (Msg 'starting')
    if ($box) {
      if ($box.ImageId -ne $imageId) { Say 'step' (Msg 'updating'); $recreate = $true }
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

  $started = First-Line (Dk inspect $Name --format '{{.State.StartedAt}}').Out '^\d{4}-'
  $since = $started
  if ($started.Length -ge 19) { $since = $started.Substring(0, 19) + 'Z' }
  $key = Wait-Ready $since $attach
  if (-not $key) { Wait-Close; return }

  $url = 'http://127.0.0.1:' + $box.Port
  Write-Host ''
  Say 'ok' (Msg 'ready' ($url + '/?key=' + $key))
  Say 'plain' (Msg 'opening')
  Open-Url ($url + '/?key=' + $key)

  Save-Copy
  if ($OnWindows) {
    $asked = Join-Path $AppDir 'icon-asked'
    if (-not (Test-Path $asked) -and (Test-Path $LocalCopy)) {
      if (Ask (Msg 'icon_q') $true) { if (New-Icon) { Say 'ok' (Msg 'icon_ok') } }
      try { Set-Content -Path $asked -Value 'yes' } catch {}
    }
  }

  Write-Host ''
  [void](Read-Host (Msg 'stop_hint'))
  Say 'step' (Msg 'stopping')
  [void](Dk stop -t 30 $Name)
  Say 'ok' (Msg 'stopped')
  Start-Sleep -Seconds 2
}
finally {
  Write-Progress -Activity 'Freefield' -Completed
  if ($prevEnc) { try { [Console]::OutputEncoding = $prevEnc } catch {} }
}
} $PSCommandPath @($args)
