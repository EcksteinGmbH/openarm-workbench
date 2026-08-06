# Damiao电机调试工具 - Windows部署指南

## 🚀 Windows系统部署安装

### 系统要求

- **Windows 10/11** (推荐) 或 **Windows 7/8**
- **Python 3.8+** (Python 3.9 推荐使用Python官方安装器)
- **空闲USB端口** (用于串口连接)
- **管理员权限** (用于安装和配置)

---

## 🔧 方法一：图形界面安装（推荐）

### 第一步：安装Python

1. 下载Python安装包
   - 访问: https://www.python.org/downloads/
   - 下载最新版Python (3.9+)

2. 安装Python
   - 双击安装包
   - **勾选"Add Python to PATH"** (重要！)
   - 选择"Install Now"

3. 验证安装
   ```cmd
   python --version
   pip --version
   ```

### 第二步：安装项目依赖

```cmd
# 进入项目目录
cd C:\path\to\OpenARM

# 安装基础依赖
pip install -r requirements.txt

# 安装Web依赖
pip install -r web/requirements.txt
```

### 第三步：安装串口工具

#### 选项1：安装PuTTY
1. 下载: https://www.chiark.greenend.org.uk/~sgtatham/putty/latest.html
2. 安装PuTTY
3. 进入PuTTY目录，安装PLINK到系统PATH

#### 选项2：使用系统自带工具
Windows已自带`cmd`和`powershell`，无需额外安装

### 第四步：配置串口权限

#### 创建批处理文件
创建一个名为`setup_permissions.bat`的文件：

```bat
@echo off
echo 配置串口权限...
echo 正在创建Python Scripts目录...

:: 检查是否存在Python Scripts目录
if not exist "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python39\Scripts" (
    echo Python Scripts目录不存在，请检查Python安装
    pause
    exit
)

:: 将串口工具复制到Python Scripts目录
copy "C:\Program Files\Putty\plink.exe" "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python39\Scripts\"

echo 串口权限配置完成！
echo 现在可以使用串口命令了
pause
```

### 第五步：启动Web服务

```cmd
# 方法1：手动启动
cd web
python app.py

# 方法2：使用启动脚本（如果已创建）
start_web.bat
```

访问: http://localhost:5000

---

## 📦 方法二：离线安装（无网络环境）

### 第一步：准备离线依赖

#### 创建离线包
```cmd
# 在联网环境下创建离线依赖包
pip download -r requirements.txt -d dependencies/
pip download -r web/requirements.txt -d web_dependencies/
```

#### 压缩离线包
创建一个`offline_installer.bat`文件：

```bat
@echo off
echo 准备离线安装包...

:: 创建目录结构
mkdir offline_packages
mkdir offline_packages\python_deps
mkdir offline_packages\web_deps

:: 复制依赖包
copy dependencies\* offline_packages\python_deps\
copy web_dependencies\* offline_packages\web_deps\

:: 复制依赖文件
copy requirements.txt offline_packages\
copy web\requirements.txt offline_packages\web_deps\

echo 离线包准备完成！
echo 将offline_packages目录复制到目标机器即可离线安装
pause
```

### 第二步：离线安装

```cmd
# 在目标机器上执行
cd offline_packages

# 安装Python依赖
pip install --no-index --find-links=python_deps -r requirements.txt

# 安装Web依赖
pip install --no-index --find-links=web_deps -r web_dependencies/requirements.txt
```

---

## ⚙️ 系统配置

### 串口配置

#### Windows串口路径查找
```cmd
# 查看可用串口
wmic path win32_serialport get name,deviceid

# 或使用PowerShell
Get-WmiObject Win32_SerialPort
```

#### 常见串口路径
- COM1 - COM9: 直接使用
- COM10+: 需要\\.\前缀，如`\\.\COM10`

### 环境变量配置

#### 创建环境变量
1. 右键"此电脑" → "属性" → "高级系统设置"
2. 点击"环境变量"
3. 在"用户变量"中添加：
   - 变量名: `DAMIAO_SERIAL_PORT`
   - 变量值: `COM3` (根据实际串口)

#### 添加到PATH
1. 在"系统变量"中找到`Path`
2. 点击"编辑"
3. 添加Python Scripts路径：
   - `C:\Users\用户名\AppData\Local\Programs\Python\Python39\Scripts\`

---

## 🔌 启动脚本

### 创建启动脚本 (start_web.bat)

```bat
@echo off
echo 🚀 启动Damiao电机调试工具...

:: 设置串口路径（如果未设置）
if not defined DAMIAO_SERIAL_PORT (
    set DAMIAO_SERIAL_PORT=COM3
    echo 使用默认串口: COM3
) else (
    echo 使用配置串口: %DAMIAO_SERIAL_PORT%
)

:: 切换到Web目录
cd /d "%~dp0web"

:: 启动Web服务
echo 启动Web服务器...
echo 访问地址: http://localhost:5000
echo 按Ctrl+C停止服务
echo.

python app.py

echo.
echo 服务已停止
pause
```

### 创建测试脚本 (test_connection.bat)

```bat
@echo off
echo 🔌 测试串口连接...

:: 检查Python安装
python --version
if %ERRORLEVEL% NEQ 0 (
    echo Python未安装，请先安装Python
    pause
    exit /b 1
)

:: 检查依赖
python -c "import flask"
if %ERRORLEVEL% NEQ 0 (
    echo 缺少依赖，请安装: pip install -r requirements.txt -r web/requirements.txt
    pause
    exit /b 1
)

:: 检查串口
echo.
echo 检查串口设备...
wmic path win32_serialport get name,deviceid

echo.
echo 请确认串口设备存在并可用
pause
```

---

## 🚨 故障排除

### 常见问题

#### 1. Python不是内部或外部命令
**解决方案:**
```bat
:: 重新安装Python，勾选"Add Python to PATH"
:: 或手动添加Python到PATH
set PATH=%PATH%;C:\Python39\
set PATH=%PATH%;C:\Python39\Scripts\
```

#### 2. 串口被占用
**解决方案:**
```cmd
:: 查找占用串口的进程
handle.exe -p COM3
:: 或使用PowerShell
Get-Process | Where-Object {$_.Handles} | ForEach-Object { 
    $handles = Get-ProcessHandle $_.Id
    $handles | Where-Object {$_.Name -like "*COM3"} | Select-Object -Property "Id","Name"
}
```

#### 3. 权限错误
**解决方案:**
```bat
:: 以管理员身份运行命令提示符
:: 或创建权限设置脚本 (setup_permissions.bat)
```

#### 4. 端口被占用
**解决方案:**
```cmd
netstat -ano | findstr :5000
:: 找到进程ID后
taskkill /F /PID 进程ID
```

### 调试模式启动

```cmd
:: 启用详细日志
cd web
set FLASK_ENV=development
set FLASK_DEBUG=1
python app.py
```

---

## 📊 服务管理

### 创建服务管理脚本

#### 启动脚本 (start_services.bat)
```bat
@echo off
echo 🚀 启动Damiao电机服务...

:: 检查Web服务是否已启动
netstat -ano | findstr :5000 >nul
if %ERRORLEVEL% EQU 0 (
    echo Web服务已在运行
) else (
    echo 启动Web服务...
    start /min python web/app.py
)

:: 启动监控服务
echo 启动数据监控服务...
start /min python examples/monitor_service.py

echo 所有服务启动完成
pause
```

#### 停止脚本 (stop_services.bat)
```bat
@echo off
echo 🛑 停止Damiao电机服务...

:: 查找并停止Python进程
taskkill /F /IM python.exe /FI "WINDOWTITLE eq *Damiao*"

echo 服务已停止
pause
```

---

## 🔄 自动更新

### 创建更新脚本 (update.bat)

```bat
@echo off
echo 🔄 更新Damiao电机调试工具...

:: 备份当前版本
mkdir backup
copy *.py backup\
copy web\*.* backup\web\

:: 从GitHub拉取最新版本
echo 从GitHub更新代码...
git pull

:: 更新依赖
pip install -r requirements.txt -r web/requirements.txt

echo 更新完成！
pause
```

---

## 📞 技术支持

### 日志查看
```cmd
# 查看Web服务日志
type web\logs\web.log

# 查看Python错误
type error.log
```

### 性能监控
```cmd
# 查看系统资源
wmic cpu get loadpercentage
wmic os get totalvisiblememorysize,freephysicalmemory

# 查看Python进程
tasklist /FI "IMAGENAME eq python.exe"
```

### 联系支持
- 用户指南: `docs/USER_GUIDE.md`
- 技术文档: `docs/SDK_RESEARCH.md`
- Web界面文档: `web/README.md`

---

## 🎯 快速开始

### 最简启动流程
```cmd
# 1. 安装Python (勾选Add to PATH)
# 2. 进入项目目录
cd C:\path\to\OpenARM

# 3. 安装依赖
pip install -r requirements.txt -r web\requirements.txt

# 4. 启动Web服务
start_web.bat

# 5. 浏览器访问
http://localhost:5000
```

完成！现在可以通过Web界面配置和控制damiao电机了。