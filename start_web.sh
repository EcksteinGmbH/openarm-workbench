#!/bin/bash

# Damiao电机Web调试工具启动脚本

echo "======================================"
echo "Damiao电机Web调试工具"
echo "======================================"
echo ""

# 检查Python版本
python3 --version

# 检查是否安装了依赖
echo ""
echo "检查依赖..."
if ! python3 -c "import flask" 2>/dev/null; then
    echo "正在安装Flask依赖..."
    cd web
    pip install -r requirements.txt
    cd ..
    echo "依赖安装完成"
else
    echo "依赖已安装"
fi

# 启动服务器
echo ""
echo "启动Web服务器..."
echo "访问地址: http://localhost:5000"
echo "按 Ctrl+C 停止服务器"
echo ""

cd web
python3 app.py
