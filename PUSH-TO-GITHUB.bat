@echo off
setlocal
title Push Qwen3.8 setup to GitHub (private)
cd /d "%~dp0"
set REPO=qwen38-27b-rtx5090

echo ============================================================
echo  Pushing this folder to a PRIVATE GitHub repo: %REPO%
echo ============================================================
echo.

where gh >nul 2>&1
if errorlevel 1 (
  echo [!] GitHub CLI not found. Install from https://cli.github.com/ then re-run.
  pause & exit /b 1
)

gh auth status >nul 2>&1
if errorlevel 1 (
  echo [*] Not logged in to GitHub. Opening login...
  gh auth login
)

for /f "delims=" %%i in ('git config --global user.name') do set GN=%%i
if "%GN%"=="" (
  echo [*] Setting git identity from your GitHub account...
  for /f "delims=" %%u in ('gh api user --jq .login') do git config --global user.name "%%u"
  for /f "delims=" %%u in ('gh api user --jq .login') do git config --global user.email "%%u@users.noreply.github.com"
)

if not exist .git (
  git init -b main
)
git add -A
git commit -m "Qwen3.8-27B NVFP4 on RTX 5090: validated vLLM setup, benchmarks, and battle log" || echo (nothing new to commit)

gh repo view %REPO% >nul 2>&1
if errorlevel 1 (
  echo [*] Creating private repo %REPO%...
  gh repo create %REPO% --private --source=. --remote=origin --push
) else (
  echo [*] Repo exists, pushing...
  git remote get-url origin >nul 2>&1 || gh repo set-default %REPO%
  git remote get-url origin >nul 2>&1 || git remote add origin https://github.com/%USERNAME%/%REPO%.git
  git push -u origin main
)

echo.
echo ============================================================
gh repo view %REPO% --json url --jq .url
echo  Share that URL with your brother, then add him as a collaborator:
echo    gh repo add-collaborator %REPO% HIS-GITHUB-USERNAME
echo ============================================================
pause
