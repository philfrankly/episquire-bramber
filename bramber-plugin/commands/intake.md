---
description: Launch the browser-based intake form for depositing files and links into _bramber/inbox/.
---

Open the intake form, reusing an existing server if one is already running.

The intake server ships in the installed `bramber` package (`bramber.intake_server`); it must be
launched with `BRAMBER_ROOT` set to the current project so deposits land in *this* project's
`_bramber/inbox/`. Run this via the PowerShell tool:

```
$alive = $false; try { Invoke-WebRequest -Uri http://localhost:47825/ -UseBasicParsing -TimeoutSec 1 | Out-Null; $alive = $true } catch {}; if ($alive) { Start-Process http://localhost:47825; 'reused existing server' } else { $env:BRAMBER_ROOT = (Get-Location).Path; Start-Process -FilePath python -ArgumentList '-m','bramber.intake_server' -WindowStyle Hidden; 'started new server' }
```

Tell the user briefly which path executed (reused vs. started new) and that the browser tab
should open in a moment. Files and links land in `_bramber/inbox/`; run `/bramber:orchestrate`
next to normalize and route them.

The server self-terminates ~90s after the last browser heartbeat, and sends an immediate
shutdown beacon when the tab closes — so closed tabs and crashed browsers clean themselves
up. It runs on port 47825, clear of the rest of the 4782x band, so several projects can run
their intake servers side by side.

If the user handed you links or files directly in chat instead, skip the server: fetch and
normalize them yourself per FORMAT-SPEC § Inbox Deposit (fetcher hints there), write them
into `_bramber/inbox/`, and continue to `/bramber:orchestrate`.
