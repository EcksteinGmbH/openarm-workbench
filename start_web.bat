# Windows启动脚本

@echo off
chcp 65001 > nul
color 0A
title Damiao电机调试工具 - Windows启动

echo ================================================
echo 🔧 Damiao电机调试工具 - Windows启动脚本
echo ================================================
echo.

:: 检查Python是否已安装
python --version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo ✅ Python已安装
    python --version
) else (
    echo ❌ Python未安装
    echo 请先安装Python 3.8+ (https://www.python.org/downloads/)
    echo 安装时请勾选"Add Python to PATH"
    pause
    exit /b 1
)

echo.
:: 检查Python路径
for /f "tokens=*" %%i in ('python -c "import sys; print(sys.executable)"') do PYTHON_PATH=%%i
echo Python路径: %PYTHON_PATH%

:: 检查依赖是否已安装
echo.
python -c "import flask" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo ✅ Flask依赖已安装
) else (
    echo ❌ Flask依赖未安装
    echo 正在安装依赖...
    pip install flask flask-cors flask-socketio
    if %ERRORLEVEL% NEQ 0 (
        echo ❌ 依赖安装失败
        pause
        exit /b 1
    )
    echo ✅ 依赖安装完成
)

echo.
:: 检查串口
echo 🔌 检查可用串口...
wmic path win32_serialport get name,deviceid 2>nul | findstr /r "COM" > available_ports.txt

if %ERRORLEVEL% EQU 0 (
    echo ✅ 检测到串口设备:
    type available_ports.txt
    echo.
    echo 💡 如果串口名称正确，直接按回车开始
    echo 💡 如果需要修改串口，请输入新名称 (如 COM3)
) else (
    echo ⚠️  未检测到串口设备
    echo 请检查:
    echo 1. USB转串口是否已连接
    echo 2. 串口驱动是否已安装
    echo 3. 是否需要手动指定串口名称
    echo.
    set /p SERIAL_PORT="请输入串口名称 (如 COM3): "
)

if not defined SERIAL_PORT (
    set /p SERIAL_PORT="请输入串口名称 (默认COM3): "
    if "%SERIAL_PORT%"=="" set SERIAL_PORT=COM3
)

echo.
echo 🚀 启动Web服务器...
echo 串口设置: %SERIAL_PORT%
echo 访问地址: http://localhost:5000
echo 按Ctrl+C停止服务
echo.

:: 创建临时配置文件
echo DAMIAO_SERIAL_PORT=%SERIAL_PORT% > config.env

:: 启动Web服务
cd /d "%~dp0web"
set FLASK_APP=app.py
set FLASK_ENV=development

:: 启动Python服务
python app.py

echo.
echo 服务已停止
pause
