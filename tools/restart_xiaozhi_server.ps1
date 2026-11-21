# Restart the xiaozhi server: kill all app.py python processes (excluding uvicorn)
# ⚠️ xiaozhi-server 在 Windows 上是「主进程(venv python)+ spawn 的 worker 子进程」结构,
#    进程列表会看到两个 app.py python——这是正常的!不要只杀其中一个(会带走整个服务)。
#    本脚本全杀后需重新拉起:用 start_xiaozhi_hidden.vbs(启动文件夹里有同名自启副本)。
Get-CimInstance Win32_Process -Filter "name='python.exe'" | Where-Object { $_.CommandLine -like '*app.py*' -and $_.CommandLine -notlike '*uvicorn*' } | ForEach-Object { Write-Output ("KILL " + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force }
