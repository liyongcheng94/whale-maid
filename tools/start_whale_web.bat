@echo off
REM web 版小鲸灵(生日保底+学园)持久化启动:uvicorn 8100
cd /d D:\project\whale-maid\web\backend
D:\project\whale-maid\web\backend\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8100 >> D:\esp\web_autostart.log 2>&1
