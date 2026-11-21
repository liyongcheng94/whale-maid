# Restart xiaozhi server: kill all app.py python processes (exclude uvicorn).
# NOTE (ASCII only - PowerShell 5.1 misparses UTF-8 files without BOM):
# xiaozhi-server on Windows runs as [venv main process + spawned worker],
# so TWO python app.py entries in the process list are NORMAL.
# Do NOT kill just one of them (it takes down the whole service).
# After this script, relaunch via start_xiaozhi_hidden.vbs (autostart copy lives in the Startup folder).
Get-CimInstance Win32_Process -Filter "name='python.exe'" | Where-Object { $_.CommandLine -like '*app.py*' -and $_.CommandLine -notlike '*uvicorn*' } | ForEach-Object { Write-Output ("KILL " + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force }
