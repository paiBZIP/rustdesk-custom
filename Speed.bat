@echo off
chcp 65001 >nul
title RustDesk Network Speed and Benchmark Tool
cd /d "%~dp0"
start "" pythonw "%~dp0Speed.py"
exit
