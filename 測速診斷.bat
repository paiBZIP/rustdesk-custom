@echo off
chcp 65001 >nul
title RustDesk 網路質量、埠號檢測與雙機測速工具 (Speed.py)
cd /d "%~dp0"
start "" pythonw "%~dp0Speed.py"
exit
