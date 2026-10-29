@echo off
rem Runs every offline test suite (fake Gemini + fake Telegram, DB copies only). No API calls, no chats touched.
cd /d %~dp0
set PY=..\.venv\Scripts\python.exe
for %%t in (test_escalation.py test_pause.py test_1026.py test_runner.py) do (
  echo == %%t
  %PY% -X utf8 %%t 2>&1 | findstr /R /C:"passed" /C:"^FAIL" /C:"^PASS playbooks" /C:"Traceback"
)
echo == test_selfplay.py (with ZEROLEAK_SELF_PLAY=1)
set ZEROLEAK_SELF_PLAY=1
%PY% -X utf8 test_selfplay.py 2>&1 | findstr /R /C:"passed" /C:"^FAIL" /C:"Traceback"
