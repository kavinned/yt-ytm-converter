Set-Location $PSScriptRoot
$ExitCode = 0

try {
    $Py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    $Ytma = Join-Path $PSScriptRoot ".venv\Scripts\ytmusicapi.exe"
    if (-not (Test-Path $Py)) {
        throw "Missing .venv. Run: python -m venv .venv; .venv\Scripts\pip install -r requirements.txt"
    }

    $Url = (Read-Host "Playlist URL or ID").Trim()
    if (-not $Url) {
        throw "No playlist URL or ID provided."
    }

    function Test-BrowserAuth {
        if (-not (Test-Path "browser.json")) { return $false }
        & $Py -c "import sys; from ytmusicapi import YTMusic; y=YTMusic('browser.json'); pl=y.get_library_playlists(limit=1); sys.exit(0 if len(pl) > 0 else 1)" 2>$null
        return ($LASTEXITCODE -eq 0)
    }

    Write-Host "Checking browser.json credentials..."
    if (-not (Test-BrowserAuth)) {
        Write-Host "Credentials missing or expired. Launching 'ytmusicapi browser'..."
        & $Ytma browser
        if ($LASTEXITCODE -ne 0) {
            $ExitCode = $LASTEXITCODE
            throw "ytmusicapi browser exited with code $ExitCode"
        }
        & $Py -c "import json, pathlib; p=pathlib.Path('browser.json'); tmp=p.with_suffix('.tmp'); d=json.loads(p.read_text(encoding='utf-8')); [d.pop(k,None) for k in ['/youtubei/v1/browse?prettyPrint=false','music.youtube.com','content-encoding']]; tmp.write_text(json.dumps(d,indent=2),encoding='utf-8'); tmp.replace(p)"
        if ($LASTEXITCODE -ne 0) {
            $ExitCode = $LASTEXITCODE
            throw "Failed to normalize browser.json (exit code $ExitCode)"
        }
    }

    $Choice = (Read-Host "Choose: [1] Preview (default)  [2] Apply  [3] Pick + Apply").Trim()
    $ArgsList = @("-m", "ytm_clean", $Url)
    if ($Choice -eq "2") {
        $ArgsList += "--apply"
    } elseif ($Choice -eq "3") {
        $ArgsList += @("--pick", "--apply")
    }

    & $Py @ArgsList
    $ExitCode = $LASTEXITCODE
}
catch {
    Write-Host "Error: $_" -ForegroundColor Red
    if ($ExitCode -eq 0) { $ExitCode = 1 }
}
finally {
    Read-Host "Press Enter to exit"
}

exit $ExitCode
