@echo off
REM go-music-dl web 服务持久化启动(8099,在线点歌后端)
cd /d D:\project\whale-maid\tools\music-dl
music-dl.exe web -p 8099 --no-browser >> D:\esp\musicdl_autostart.log 2>&1
