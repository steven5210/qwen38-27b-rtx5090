@echo off
setlocal enabledelayedexpansion
title Qwen3.8-27B - Ask
cd /d "%~dp0"

:menu
cls
echo ================================================================
echo    Qwen3.8-27B   ask a question
echo ================================================================
echo.
echo   Pick a mode. The numbers next to each are measured on this
echo   machine, not guesses - see README.md for how.
echo.
echo   [1] QUICK          medium effort, 16,384 tokens
echo                      RECOMMENDED. Scored 24/24 and 8/8 in every
echo                      test here. Typically 20-60 seconds.
echo.
echo   [2] DEEP THINK     xhigh effort, 90,000 tokens
echo                      For one genuinely hard problem. 4-10 minutes.
echo                      Needs a SMALL prompt or it truncates.
echo                      Never beat medium in our testing.
echo.
echo   [3] FAST           low effort, 8,192 tokens
echo                      Snappier, but low is NOT reliably faster
echo                      end-to-end - it skips planning and rambles.
echo.
echo   [4] NO THINKING    thinking disabled, 8,192 tokens
echo                      Fastest first token (~0.15s). Best for
echo                      simple lookups and short code snippets.
echo.
echo   [5] CUSTOM         choose effort and token budget yourself
echo.
echo   [6] What do these actually cost?  (show the measured data)
echo.
echo   [Q] Quit
echo.
set "CHOICE="
set /p "CHOICE=Select [1-6, Q]: "

if /i "!CHOICE!"=="Q" exit /b 0
if "!CHOICE!"=="1" ( set "EFF=medium" & set "MAXT=16384" & goto ask )
if "!CHOICE!"=="2" ( set "EFF=xhigh"  & set "MAXT=90000" & goto ask )
if "!CHOICE!"=="3" ( set "EFF=low"    & set "MAXT=8192"  & goto ask )
if "!CHOICE!"=="4" ( set "EFF=off"    & set "MAXT=8192"  & goto ask )
if "!CHOICE!"=="5" goto custom
if "!CHOICE!"=="6" goto data
goto menu

:data
cls
echo ================================================================
echo   Measured on this machine (RTX 5090, 104K context)
echo ================================================================
echo.
echo   ACCURACY - same unit-tested problems, same session:
echo      medium ....... 24/24 code, in 360 seconds
echo      xhigh ........  9/24 code, in 1,533 seconds
echo      Every xhigh failure was TRUNCATION, never a wrong answer.
echo.
echo   HOW MUCH ROOM xhigh NEEDS (it stops when it is ready):
echo      15,493 / 21,500 / 25,686 / 41,356 / more than 48,000 tokens
echo      Median 23,593. That 3x spread is why no single setting works.
echo.
echo   SPEED - decode rate by effort:
echo      no thinking .. ~115 tokens/sec
echo      medium ....... ~89 tokens/sec
echo      xhigh ........ ~65 tokens/sec
echo      xhigh is slower per token AND writes 3-4x more of them.
echo.
echo   WHY: speculative-decode acceptance falls from 96%% on plain
echo   code to 34%% on deep reasoning - reasoning tokens are simply
echo   less predictable to the draft head.
echo.
echo   BOTTOM LINE: use [1] QUICK. Reach for [2] only when medium
echo   has already given you an answer you do not believe.
echo.
pause
goto menu

:custom
cls
echo   CUSTOM
echo.
echo   Effort:  xhigh ^| medium ^| low ^| off
echo   (default is xhigh if you just press Enter - that is the
echo    model's own default, and it is rarely what you want)
echo.
set "EFF="
set /p "EFF=Effort [medium]: "
if "!EFF!"=="" set "EFF=medium"
echo.
echo   Token budget. Reference points from our testing:
echo      8,192  - plenty for no-thinking or short answers
echo     16,384  - fine for medium; xhigh truncates here about half the time
echo     48,000  - covers most xhigh runs, one problem still exceeded it
echo     90,000  - xhigh finishes, needs a small prompt
echo.
set "MAXT="
set /p "MAXT=Max tokens [16384]: "
if "!MAXT!"=="" set "MAXT=16384"
goto ask

:ask
cls
echo ================================================================
echo   effort = !EFF!      max tokens = !MAXT!
echo ================================================================
echo.
set "ATTACH="
set /p "ATTACH=File to attach (full path, or Enter to skip): "
echo.
echo   Your question (single line, then Enter):
echo.
set "Q="
set /p "Q=> "
if "!Q!"=="" ( echo. & echo   Nothing asked. & pause & goto menu )

echo.
echo ----------------------------------------------------------------
if "!ATTACH!"=="" (
  wsl -d Ubuntu-26.04 -u root --cd "%~dp0" -- /opt/qwen38/venv/bin/python ask-xhigh.py --effort !EFF! --max-tokens !MAXT! "!Q!"
) else (
  wsl -d Ubuntu-26.04 -u root --cd "%~dp0" -- /opt/qwen38/venv/bin/python ask-xhigh.py --effort !EFF! --max-tokens !MAXT! --file "!ATTACH!" "!Q!"
)
echo ----------------------------------------------------------------
echo.
set "AGAIN="
set /p "AGAIN=Ask another? [y/N]: "
if /i "!AGAIN!"=="y" goto menu
exit /b 0
