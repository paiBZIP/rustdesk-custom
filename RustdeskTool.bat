@echo off
chcp 65001 >nul
title RustDesk Client Customization Tool
cd /d "%~dp0"
start "" pythonw "%~dp0RustdeskTool.py"
exit
