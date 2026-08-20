@echo off
setlocal EnableDelayedExpansion
title RailCrowd - Deploy to Vercel
cd /d "%~dp0"

echo ============================================================
echo   RailCrowd  —  one-click Vercel deploy (Windows)
echo ============================================================
echo.

rem ------------------------------------------------------------
rem 1) Node.js is required for the Vercel CLI
rem ------------------------------------------------------------
where node >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Node.js not found. Install it from https://nodejs.org
    echo         then run this file again.
    pause
    exit /b 1
)
echo [OK] Node.js found.

rem ------------------------------------------------------------
rem 2) Vercel CLI (install globally if missing)
rem ------------------------------------------------------------
where vercel >nul 2>nul
if errorlevel 1 (
    echo [INFO] Installing Vercel CLI (this may take a minute)...
    call npm install -g vercel
    if errorlevel 1 (
        echo [ERROR] Could not install Vercel CLI.
        pause
        exit /b 1
    )
)
echo [OK] Vercel CLI ready.

rem ------------------------------------------------------------
rem 3) Required files check
rem ------------------------------------------------------------
if not exist "vercel.json"    ( echo [ERROR] vercel.json missing    & pause & exit /b 1 )
if not exist "api\index.py"   ( echo [ERROR] api\index.py missing   & pause & exit /b 1 )
if not exist "requirements.txt" ( echo [ERROR] requirements.txt missing & pause & exit /b 1 )
echo [OK] vercel.json + api/index.py + requirements.txt present.

rem ------------------------------------------------------------
rem 4) Login + link the project
rem ------------------------------------------------------------
echo.
echo [INFO] Logging in to Vercel (a browser window will open)...
call vercel login
if errorlevel 1 ( echo [ERROR] Login failed. & pause & exit /b 1 )

echo [INFO] Linking this folder to a Vercel project...
call vercel link
if errorlevel 1 ( echo [ERROR] Linking failed. & pause & exit /b 1 )

rem ------------------------------------------------------------
rem 5) THE DATABASE  (real-time community votes / crowd rating)
rem ------------------------------------------------------------
echo.
echo ============================================================
echo  STEP 1 of 2 — attach a database so votes persist in real time
echo ============================================================
echo  Pick ONE of these (both are one-click in the dashboard):
echo.
echo   A) Vercel Postgres (recommended):
echo      - open  https://vercel.com/dashboard/stores
echo      - click "Create" ^> "Postgres" ^> link it to THIS project
echo      - Vercel auto-injects: POSTGRES_URL, POSTGRES_HOST,
echo        POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DATABASE
echo        (RailCrowd auto-creates the "reports" table on first use)
echo.
echo   B) Vercel KV (Redis, no SQL):
echo      - open  https://vercel.com/dashboard/stores
echo      - click "Create" ^> "KV Durable Redis" ^> link to THIS project
echo      - Vercel auto-injects: KV_REST_API_URL, KV_REST_API_TOKEN
echo.
echo  Without a database, reports/votes cannot be saved on Vercel.
echo.
pause

rem ------------------------------------------------------------
rem 6) Optional: push backend\.env secrets to Vercel (best effort)
rem ------------------------------------------------------------
if exist "backend\.env" (
    echo [INFO] Pushing backend\.env secrets to Vercel (production)...
    for /f "usebackq delims=" %%L in ("backend\.env") do (
        set "line=%%L"
        set "line=!line: =!"
        if not "!line!"=="" if not "!line:~0,1!"=="#" (
            for /f "tokens=1,* delims==" %%A in ("!line!") do (
                set "k=%%A"
                set "v=%%B"
                set "v=!v:"=!"
                if not "!v!"=="" (
                    echo   - !k!
                    echo !v!| call vercel env add !k! production
                )
            )
        )
    )
    echo [INFO] If any secret failed above, add it manually:
    echo        vercel env add NAME production
) else (
    echo [INFO] No backend\.env found. Add optional live-data keys manually:
    echo        vercel env add NTES_API_BASE production
    echo        vercel env add OPENWEATHER_API_KEY production
)

rem ------------------------------------------------------------
rem 7) Deploy to production
rem ------------------------------------------------------------
echo.
echo ============================================================
echo  STEP 2 of 2 — deploy
echo ============================================================
echo [INFO] Deploying to production...
call vercel --prod --force
if errorlevel 1 ( echo [ERROR] Deploy failed — check the log above. & pause & exit /b 1 )

echo.
echo ============================================================
echo  VERIFY THE DEPLOYMENT
echo ============================================================
echo  Open this in your browser (replace YOUR-APP with your domain):
echo     https://YOUR-APP.vercel.app/
echo  and this JSON health check:
echo     https://YOUR-APP.vercel.app/api/health
echo.
echo  Expected in /api/health:
echo     "frontend": true          <- homepage will load
echo     "storage": "postgres" or "kv"   <- votes persist in real time
echo.
echo  If the homepage still shows "Not Found":
echo     1. Run:  vercel logs YOUR-APP.vercel.app
echo     2. Confirm the project ROOT is the railcrowd folder
echo        (it must contain vercel.json + api\index.py + frontend\ + backend\).
echo     3. Re-deploy with this script (it now uses --force).
echo ============================================================
pause
