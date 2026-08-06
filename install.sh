#!/bin/bash

# Damiao电机调试工具 - 一键安装部署脚本
# 支持Ubuntu/Debian/CentOS系统

set -e

echo "================================================"
echo "🔧 Damiao电机调试工具 - 一键安装部署脚本"
echo "================================================"
echo ""

# 检查是否为root用户
if [ "$EUID" -ne 0 ]; then
    echo "⚠️  建议使用root权限执行此脚本"
    echo "💡 使用: sudo $0"
    echo ""
fi

# 检测系统
detect_system() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$NAME
        VERSION=$VERSION_ID
        echo "检测到系统: $OS $VERSION"
    else
        echo "❌ 无法检测系统版本"
        exit 1
    fi
}

# 检查是否为支持的系统
check_system() {
    echo "检查系统兼容性..."
    
    case "$ID" in
        ubuntu|debian)
            OS_TYPE="debian"
            echo "✅ 支持的Debian/Ubuntu系统"
            ;;
        centos|rhel)
            OS_TYPE="redhat"
            echo "✅ 支持的CentOS/RHEL系统"
            ;;
        *)
            echo "❌ 不支持的系统: $ID"
            echo "支持的系统: Ubuntu, Debian, CentOS, RHEL"
            exit 1
            ;;
    esac
}

# 安装Python和pip
install_python() {
    echo "📦 安装Python 3和pip..."
    
    case "$OS_TYPE" in
        debian)
            apt update -qq
            apt install -y python3 python3-pip python3-venv python3-dev build-essential
            ;;
        redhat)
            yum update -y
            yum install -y python3 python3-pip python3-devel gcc gcc-c++ make
            ;;
    esac
    
    # 验证安装
    python3 --version
    pip3 --version
}

# 安装串口工具
install_serial_tools() {
    echo "🔌 安装串口工具..."
    
    case "$OS_TYPE" in
        debian)
            apt install -y minicom screen
            ;;
        redhat)
            yum install -y minicom screen
            ;;
    esac
    
    echo "✅ 串口工具安装完成"
}

# 创建服务用户
create_user() {
    echo "👤 创建服务用户..."
    
    if ! id "damiao_user" &>/dev/null; then
        useradd -m -s /bin/bash damiao_user
        echo "✅ 用户 damiao_user 创建成功"
    else
        echo "✅ 用户 damiao_user 已存在"
    fi
    
    # 添加用户到dialout组（串口访问权限）
    usermod -a -G dialout damiao_user
    echo "✅ 用户已添加到dialout组"
}

# 设置串口权限
setup_serial_permissions() {
    echo "⚙️  配置串口权限..."
    
    # 创建udev规则
    cat > /etc/udev/rules.d/99-damiao-motor.rules << EOF
# Damiao电机串口权限规则
KERNEL=="ttyUSB*", GROUP="dialout", MODE="0660"
KERNEL=="ttyACM*", GROUP="dialout", MODE="0660"
SUBSYSTEM=="tty", KERNEL=="tty*", ACTION=="add", RUN+="/bin/chgrp dialout %m", RUN+="/bin/chmod 0660 %m"
EOF

    # 重新加载udev规则
    udevadm control --reload-rules
    udevadm trigger
    echo "✅ 串口权限配置完成"
}

# 安装Python依赖
install_python_dependencies() {
    echo "🐍 安装Python依赖包..."
    
    # 升级pip
    pip3 install --upgrade pip
    
    # 安装基础依赖
    pip3 install -r requirements.txt
    
    # 安装Web依赖
    if [ -f "web/requirements.txt" ]; then
        pip3 install -r web/requirements.txt
    fi
    
    echo "✅ Python依赖安装完成"
}

# 创建目录结构
setup_directories() {
    echo "📁 创建项目目录结构..."
    
    # 创建运行目录
    mkdir -p /opt/damiao-motor
    mkdir -p /opt/damiao-motor/logs
    mkdir -p /opt/damiao-motor/backups
    mkdir -p /var/lib/damiao-motor
    
    # 复制项目文件
    cp -r . /opt/damiao-motor/
    chown -R damiao_user:damiao_user /opt/damiao-motor/
    
    echo "✅ 目录结构创建完成"
}

# 创建服务文件
create_service_files() {
    echo "🔧 创建系统服务文件..."
    
    # Web服务
    cat > /etc/systemd/system/damiao-web.service << EOF
[Unit]
Description=Damiao Motor Web Service
After=network.target

[Service]
Type=simple
User=damiao_user
WorkingDirectory=/opt/damiao-motor/web
ExecStart=/usr/bin/python3 app.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

    # 创建启动脚本
    cat > /opt/damiao-motor/start-all.sh << 'EOF'
#!/bin/bash
echo "🚀 启动Damiao电机调试工具..."

# 启动Web服务
echo "启动Web服务..."
cd /opt/damiao-motor/web
nohup python3 app.py > ../logs/web.log 2>&1 &
WEB_PID=$!

# 等待服务启动
sleep 3

echo "✅ Web服务已启动 (PID: $WEB_PID)"
echo "访问地址: http://localhost:5000"
echo ""
echo "停止服务: /opt/damiao-motor/stop-all.sh"

# 保存PID
echo $WEB_PID > /opt/damiao-motor/web.pid

echo "🎉 所有服务启动完成！"
EOF

    # 创建停止脚本
    cat > /opt/damiao-motor/stop-all.sh << 'EOF'
#!/bin/bash
echo "🛑 停止Damiao电机调试工具..."

# 停止Web服务
if [ -f "/opt/damiao-motor/web.pid" ]; then
    WEB_PID=$(cat /opt/damiao-motor/web.pid)
    if kill -0 $WEB_PID 2>/dev/null; then
        echo "停止Web服务 (PID: $WEB_PID)"
        kill $WEB_PID
    fi
    rm -f /opt/damiao-motor/web.pid
fi

echo "✅ 所有服务已停止"
EOF

    # 创建状态检查脚本
    cat > /opt/damiao-motor/status.sh << 'EOF'
#!/bin/bash
echo "📊 Damiao电机调试工具状态检查"

# 检查Web服务
if [ -f "/opt/damiao-motor/web.pid" ]; then
    WEB_PID=$(cat /opt/damiao-motor/web.pid)
    if kill -0 $WEB_PID 2>/dev/null; then
        echo "✅ Web服务运行中 (PID: $WEB_PID)"
    else
        echo "❌ Web服务未运行"
        rm -f /opt/damiao-motor/web.pid
    fi
else
    echo "❌ Web服务未运行"
fi

# 检查端口占用
if netstat -tlnp | grep :5000; then
    echo "✅ 端口5000已被占用"
else
    echo "❌ 端口5000未被占用"
fi

echo ""
echo "查看日志: tail -f /opt/damiao-motor/logs/web.log"
EOF

    # 设置权限
    chmod +x /opt/damiao-motor/*.sh
    
    # 重新加载systemd
    systemctl daemon-reload
    
    echo "✅ 服务文件创建完成"
}

# 配置防火墙
setup_firewall() {
    echo "🔥 配置防火墙..."
    
    if command -v ufw &> /dev/null; then
        # UFW防火墙 (Ubuntu)
        ufw allow 5000/tcp comment 'Damiao Web Service'
        ufw --force reload
        echo "✅ UFW防火墙配置完成"
    elif command -v firewall-cmd &> /dev/null; then
        # Firewalld (CentOS/RHEL)
        firewall-cmd --permanent --add-port=5000/tcp
        firewall-cmd --reload
        echo "✅ Firewalld配置完成"
    else
        echo "⚠️  未找到防火墙工具，请手动开放端口5000"
    fi
}

# 创建初始化脚本
create_init_script() {
    echo "📝 创建初始化脚本..."
    
    cat > /opt/damiao-motor/init.sh << 'EOF'
#!/bin/bash
echo "🔧 Damiao电机调试工具初始化..."

# 设置Python环境
if [ ! -d "venv" ]; then
    echo "创建Python虚拟环境..."
    python3 -m venv venv
fi

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
echo "安装依赖包..."
pip install -r requirements.txt
if [ -f "web/requirements.txt" ]; then
    pip install -r web/requirements.txt
fi

echo "✅ 初始化完成"
EOF

    chmod +x /opt/damiao-motor/init.sh
}

# 创建备份脚本
create_backup_script() {
    echo "💾 创建备份脚本..."
    
    cat > /opt/damiao-motor/backup.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="/opt/damiao-motor/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

echo "📦 创建备份: $TIMESTAMP"

# 创建备份目录
mkdir -p $BACKUP_DIR

# 备份项目文件
tar -czf $BACKUP_DIR/damiao-motor_$TIMESTAMP.tar.gz \
    --exclude=venv \
    --exclude=__pycache__ \
    --exclude=*.pyc \
    --exclude=node_modules \
    -C /opt/damiao-motor .

# 保留最近5个备份
cd $BACKUP_DIR
ls -t damiao-motor_*.tar.gz | tail -n +6 | xargs rm -f

echo "✅ 备份完成: $BACKUP_DIR/damiao-motor_$TIMESTAMP.tar.gz"
EOF

    chmod +x /opt/damiao-motor/backup.sh
}

# 显示完成信息
show_completion() {
    echo ""
    echo "================================================"
    echo "🎉 安装部署完成！"
    echo "================================================"
    echo ""
    echo "📍 安装位置: /opt/damiao-motor/"
    echo "📝 日志目录: /opt/damiao-motor/logs/"
    echo "💾 备份目录: /opt/damiao-motor/backups/"
    echo ""
    echo "🚀 快速启动:"
    echo "  1. 初始化环境: cd /opt/damiao-motor && ./init.sh"
    echo "  2. 手动启动:   cd /opt/damiao-motor/web && python3 app.py"
    echo "  3. 系统服务:   systemctl start damiao-web"
    echo "  4. 启动所有:   /opt/damiao-motor/start-all.sh"
    echo ""
    echo "📊 管理命令:"
    echo "  启动服务: /opt/damiao-motor/start-all.sh"
    echo "  停止服务: /opt/damiao-motor/stop-all.sh"
    echo "  状态检查: /opt/damiao-motor/status.sh"
    echo "  备份项目: /opt/damiao-motor/backup.sh"
    echo ""
    echo "🌐 访问地址: http://localhost:5000"
    echo ""
    echo "📚 使用文档:"
    echo "  - 用户指南: /opt/damiao-motor/docs/USER_GUIDE.md"
    echo "  - 项目文档: /opt/damiao-motor/README.md"
    echo ""
    echo "⚠️  注意事项:"
    echo "  1. 使用前请确保串口设备权限已正确配置"
    echo "  2. 首次运行请执行初始化脚本"
    echo "  3. 如遇到权限问题，使用 sudo 或联系管理员"
    echo "  4. 请定期备份数据和配置文件"
    echo ""
}

# 主安装流程
main() {
    echo "开始安装Damiao电机调试工具..."
    echo ""
    
    detect_system
    check_system
    install_python
    install_serial_tools
    create_user
    setup_serial_permissions
    install_python_dependencies
    setup_directories
    create_service_files
    setup_firewall
    create_init_script
    create_backup_script
    
    show_completion
}

# 显示菜单
show_menu() {
    echo ""
    echo "================================================"
    echo "🔧 Damiao电机调试工具 - 安装选项"
    echo "================================================"
    echo ""
    echo "1. 完整安装 (推荐)"
    echo "2. 仅安装Python依赖"
    echo "3. 仅配置串口权限"
    echo "4. 仅创建系统服务"
    echo "5. 退出"
    echo ""
    read -p "请选择安装选项 [1-5]: " choice
    
    case $choice in
        1)
            main
            ;;
        2)
            install_python_dependencies
            ;;
        3)
            setup_serial_permissions
            ;;
        4)
            create_service_files
            ;;
        5)
            echo "退出安装"
            exit 0
            ;;
        *)
            echo "无效选择，请重新输入"
            show_menu
            ;;
    esac
}

# 如果直接运行脚本，执行主流程
if [ $# -eq 0 ]; then
    show_menu
else
    # 命令行参数支持
    case "$1" in
        install)
            main
            ;;
        python-deps)
            install_python_dependencies
            ;;
        serial-perms)
            setup_serial_permissions
            ;;
        service)
            create_service_files
            ;;
        help|h)
            show_menu
            ;;
        *)
            echo "用法: $0 [install|python-deps|serial-perms|service|help]"
            exit 1
            ;;
    esac
fi