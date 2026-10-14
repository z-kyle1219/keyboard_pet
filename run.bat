@echo off
REM ============================================
REM  键盘计数桌宠 - 一键启动脚本 (Windows)
REM  会自动：找 Python -> 装依赖 -> 启动
REM ============================================
cd /d "%~dp0"

echo ============================================
echo   键盘计数桌宠 正在启动...
echo ============================================

REM 兜底：确保资源目录存在
if not exist "assets" mkdir "assets"

REM 2. 查找可用的 Python
set "PY=python"
where python >nul 2>nul
if %errorlevel%==0 (
    set "PY=python"
    goto :have_python
)
where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py -3"
    goto :have_python
)
REM 没找到系统 Python，尝试 Anaconda 常用路径
if exist "D:\Anaconda3\python.exe" (
    set "PY=D:\Anaconda3\python.exe"
    goto :have_python
)
echo [错误] 未找到 Python，请先安装 Python 3.8+。
pause
exit /b 1

:have_python
echo [1/3] 使用 Python：%PY%

REM 3. 优先 uv，其次 pip
where uv >nul 2>nul
if %errorlevel%==0 (
    echo [2/3] 使用 uv 安装依赖并启动...
    uv run python main.py
    goto :end
)

echo [2/3] 使用 pip 安装依赖...
%PY% -m pip install -r requirements.txt --quiet
echo [3/3] 启动桌宠...
%PY% main.py

:end
pause
