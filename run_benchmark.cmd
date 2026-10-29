@echo off
rem Headless benchmark: 5 matches per arm (before/after playbook). Results: bench_runs\<timestamp>\results.json
cd /d %~dp0
set GEMINI_MODEL=gemini-3.5-flash-lite
if not exist logs mkdir logs
".venv\Scripts\python.exe" -X utf8 -u src\headless_runner.py --matches 5 >> "logs\bench_run.log" 2>&1