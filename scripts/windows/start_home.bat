@echo off
chcp 65001 >nul
rem 启动小窝。参数同 Ubuntu：--mock --fast --bind IP --hub URL --port N
cd /d "%~dp0..\.."
if exist scripts\windows\home_env.bat call scripts\windows\home_env.bat
set PY=python
if exist .venv\Scripts\python.exe set PY=.venv\Scripts\python.exe
%PY% home\server.py %*
