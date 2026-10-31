@echo off
rem Runs every offline test suite (fake Gemini + fake Telegram, DB copies only). No API calls, no chats touched.
cd /d %~dp0
set PY=..\.venv\Scripts\python.exe
rem Shadow regression tests launch real headless matches (Gemini): always off offline.
set ZEROLEAK_SHADOW_MATCHES=0
for %%t in (test_escalation.py test_pause.py test_1026.py test_1030.py test_1031.py test_shadow.py test_neha_escalation.py test_runner.py) do (
  echo == %%t
  %PY% -X utf8 %%t 2>&1 | findstr /R /C:"passed" /C:"^FAIL" /C:"^PASS playbooks" /C:"Traceback"
)
echo == test_selfplay.py (with ZEROLEAK_SELF_PLAY=1)
set ZEROLEAK_SELF_PLAY=1
%PY% -X utf8 test_selfplay.py 2>&1 | findstr /R /C:"passed" /C:"^FAIL" /C:"Traceback"
