# Windows测试脚本

@echo off
chcp 65001 > nul
color 0B
title Damiao电机调试工具 - 测试工具

echo ================================================
echo 🔧 Damiao电机调试工具 - 测试工具
echo ================================================
echo.

:: 菜单选择
:menu
echo.
echo 请选择测试项目:
echo.
echo 1. 测试Python环境
echo 2. 测试依赖安装
echo 3. 测试串口连接
echo 4. 测试Web服务
echo 5. 系统诊断
echo 6. 退出
echo.
set /p choice="请输入选项 [1-6]: "

if "%choice%"=="1" goto test_python
if "%choice%"=="2" goto test_deps
if "%choice%"=="3" goto test_serial
if "%choice%"=="4" goto test_web
if "%choice%"=="5" goto diagnose
if "%choice%"=="6" exit
echo 无效选项，请重新选择
goto menu

:: 测试Python环境
:test_python
echo.
echo 🐍 测试Python环境...
echo.

python --version
if %ERRORLEVEL% EQU 0 (
    echo ✅ Python安装成功
) else (
    echo ❌ Python未安装
    echo 请从 https://www.python.org/downloads/ 安装Python
    goto end_test
)

echo.
:: 检查Python路径
for /f "tokens=*" %%i in ('python -c "import sys; print(sys.executable)"') do (
    echo Python路径: %%i
)

echo.
:: 检查Python版本
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo Python版本: %PYTHON_VERSION%

echo.
:: 检查Python位数
python -c "import struct; print('64-bit' if struct.calcsize('P') == 8 else '32-bit')" 2>nul

echo.
:: 检查pip
pip --version
if %ERRORLEVEL% EQU 0 (
    echo ✅ pip可用
) else (
    echo ❌ pip不可用，请重新安装Python
)

echo.
:: 检查PATH设置
echo 检查Python在PATH中的位置:
where python
where pip

echo.
echo ✅ Python环境测试完成
goto end_test

:: 测试依赖安装
:test_deps
echo.
echo 📦 测试Python依赖...
echo.

:: 测试基础依赖
echo 测试基础依赖:
for %%p in (numpy pyserial loguru pyyaml) do (
    python -c "import %%p" >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        echo ✅ %%p
    ) else (
        echo ❌ %%p
    )
)

echo.
:: 测试Web依赖
echo 测试Web依赖:
for %%p in (flask flask-cors flask-socketio) do (
    python -c "import %%p" >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        echo ✅ %%p
    ) else (
        echo ❌ %%p
    )
)

echo.
:: 安装缺失的依赖
echo 安装缺失的依赖...
pip install -r requirements.txt
if %ERRORLEVEL% EQU 0 (
    echo ✅ 依赖安装成功
) else (
    echo ❌ 依赖安装失败，请检查网络连接
)

echo.
echo ✅ 依赖测试完成
goto end_test

:: 测试串口连接
:test_serial
echo.
echo 🔌 测试串口连接...
echo.

:: 列出可用串口
echo 可用串口设备:
wmic path win32_serialport get name,deviceid 2>nul | findstr /r "COM"

:: 如果没有输出，显示备用信息
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ⚠️  未检测到串口设备
    echo 请检查:
    echo 1. USB转串口是否已插入
    echo 2. 串口驱动是否已安装
    echo 3. 端口是否被其他程序占用
    echo.
    echo 使用PowerShell检测串口:
    powershell -Command "Get-WmiObject Win32_SerialPort | Select-Object Name,DeviceID"
    echo.
)

:: 测试串口连通性
set /p TEST_PORT="请输入要测试的串口名称 (如 COM3): "
if "%TEST_PORT%"=="" set TEST_PORT=COM3

echo.
echo 测试串口 %TEST_PORT% 连通性...

:: 使用PuTTY测试 (如果可用)
plink -serial %TEST_PORT% -sercfg 115200 -t 2>nul
if %ERRORLEVEL% EQU 0 (
    echo ✅ 串口 %TEST_PORT% 连通性测试通过
) else (
    echo ❌ 串口 %TEST_PORT% 连通性测试失败
    echo 可能原因:
    echo 1. 串口未连接
    echo 2. 串口被占用
    echo 3. 驱动问题
    echo 4. PuTTY未安装
)

echo.
:: 使用Windows内置工具测试
echo 使用Windows内置工具测试...
echo 可以使用以下命令测试串口:
echo echo test > %TEST_PORT%

echo.
echo ✅ 串口测试完成
goto end_test

:: 测试Web服务
:test_web
echo.
echo 🌐 测试Web服务...
echo.

:: 检查Web服务是否已在运行
netstat -ano | findstr :5000 >nul
if %ERRORLEVEL% EQU 0 (
    echo ⚠️  端口5000已被占用，可能Web服务已在运行
    echo 请先停止现有服务后再测试
    goto end_test
)

echo.
:: 启动测试Web服务
echo 启动测试Web服务...
cd /d "%~dp0web"

:: 创建简单的测试Web服务
echo 创建测试服务...
echo from flask import Flask > test_web.py
echo app = Flask(__name__) >> test_web.py
.echo @app.route('/') >> test_web.py
.echo def hello(): >> test_web.py
.echo     return "Damiao Web Service Test OK" >> test_web.py
.echo if __name__ == '__main__': >> test_web.py
.echo     app.run(port=5001, debug=True, threaded=True) >> test_web.py

python test_web.py &

:: 等待服务启动
timeout /t 3 /nobreak >nul

echo.
:: 测试服务是否正常运行
echo 测试Web服务连接...
curl http://localhost:5001 >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo ✅ Web服务测试成功
    echo 浏览器访问: http://localhost:5001
) else (
    echo ❌ Web服务测试失败
)

echo.
:: 停止测试服务
echo 停止测试服务...
taskkill /F /IM python.exe /FI "WINDOWTITLE eq *test_web*" >nul 2>&1

echo.
echo ✅ Web服务测试完成
goto end_test

:: 系统诊断
:diagnose
echo.
echo 🩺 系统诊断报告
echo ================================================
echo.

echo 📋 系统信息:
echo 操作系统: ver | find "Windows"
echo 处理器信息: wmic cpu get name | findstr /v "Name"
echo 内存信息: wmic OS get TotalVisibleMemorySize,FreePhysicalMemory | findstr /v "TotalVisibleMemorySize"

echo.
echo 🔌 端口占用情况:
netstat -ano | findstr :5000
if %ERRORLEVEL% EQU 0 (
    echo ⚠️  端口5000被占用
) else (
    echo ✅ 端口5000可用
)

echo.
echo 🐍 Python环境:
python --version
pip --version

echo.
echo 📦 Python包信息:
pip list | findstr -E "(flask|numpy|pyserial)"

echo.
echo 🔌 串口信息:
wmic path win32_serialport get name,deviceid 2>nul | findstr /r "COM"

echo.
echo 💾 磁盘空间:
wmic logicaldisk get size,freespace,caption

echo.
echo ✅ 系统诊断完成
goto end_test

:end_test
echo.
echo 测试完成！按任意键返回主菜单...
pause >nul
goto menu
