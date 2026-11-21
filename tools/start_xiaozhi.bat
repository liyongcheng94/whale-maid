@echo off
REM xiaozhi 服务端持久化启动(R139b):opus.dll/ffmpeg.exe 都在 venv Scripts,PATH 必须带上
cd /d D:\project\whale-maid\src\xiaozhi-esp32-server\main\xiaozhi-server
set PATH=D:\project\whale-maid\src\xiaozhi-esp32-server\main\xiaozhi-server\.venv311\Scripts;%PATH%
D:\project\whale-maid\src\xiaozhi-esp32-server\main\xiaozhi-server\.venv311\Scripts\python.exe app.py >> D:\esp\server_autostart.log 2>&1
