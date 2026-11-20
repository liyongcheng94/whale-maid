# Restart the xiaozhi server: kill all app.py python processes (excluding uvicorn)
Get-CimInstance Win32_Process -Filter "name='python.exe'" | Where-Object { $_.CommandLine -like '*app.py*' -and $_.CommandLine -notlike '*uvicorn*' } | ForEach-Object { Write-Output ("KILL " + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force }
