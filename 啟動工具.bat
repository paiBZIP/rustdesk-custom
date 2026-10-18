@echo off
chcp 65001 >nul
title RustDesk 客戶端客製化管理工具
cd /d "%~dp0"
start "" pythonw "%~dp0RustdeskTool.py"
exit
