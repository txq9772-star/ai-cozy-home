@echo off
chcp 65001 >nul
rem 小窝：Windows 安装。需要先装 Python 3.10+（安装时勾选 Add to PATH）。
cd /d "%~dp0..\.."
python -m venv .venv || goto :err
.venv\Scripts\python -m pip install -q --upgrade pip
.venv\Scripts\python -m pip install -q -r requirements.txt || goto :err
if not exist data mkdir data
if not exist home.yaml copy home.example.yaml home.yaml >nul && echo 已生成 home.yaml，按需修改
if not exist scripts\windows\home_env.bat copy scripts\windows\home_env.example.bat scripts\windows\home_env.bat >nul
echo 装好了。试运行：scripts\windows\start_home.bat --mock --fast
pause
exit /b 0
:err
echo 安装失败，看上面的报错
pause
exit /b 1
