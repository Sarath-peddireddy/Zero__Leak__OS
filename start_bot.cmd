@echo off
rem Starts the ZeroLeak bot (Flash Lite). Output goes to logs\bot_live.log. Stop it by closing the window
rem or ending the python.exe process. Only run ONE copy: two bots would fight over Telegram updates.
cd /d %~dp0
set GEMINI_MODEL=gemini-3.5-flash-lite
if not exist logs mkdir logs
".venv\Scripts\python.exe" -X utf8 -u bot_main.py >> "logs\bot_live.log" 2>&1
