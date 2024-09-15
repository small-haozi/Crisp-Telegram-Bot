#!/bin/bash

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 服务名称
SERVICE_NAME="bot.service"

# 获取脚本所在目录
BOT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# 脚本名称
SCRIPT_NAME=$(basename "$0")

# 检查是否以root权限运行
if [ "$EUID" -ne 0 ]
  then echo -e "${RED}请以root权限运行此脚本${NC}"
  exit
fi

# 创建符号链接函数
create_symlink() {
    if [ ! -L "/usr/local/bin/crispbot" ]; then
        ln -s "$BOT_DIR/$SCRIPT_NAME" /usr/local/bin/crispbot
        echo -e "${GREEN}符号链接已创建。现在可以使用 'crispbot' 命令来运行此脚本。${NC}"
    else
        echo -e "${YELLOW}符号链接 'crispbot' 已存在。${NC}"
    fi
}

# 检查环境函数
check_environment() {
    echo -e "${YELLOW}正在检查环境...${NC}"
    
    # 检查并安装 Python3
    if ! command -v python3 &> /dev/null; then
        echo -e "${YELLOW}未检测到 Python3，正在尝试安装...${NC}"
        if [ -f /etc/debian_version ]; then
            # Debian/Ubuntu 系统
            sudo apt-get update && sudo apt-get install -y python3
        elif [ -f /etc/redhat-release ]; then
            # CentOS/RHEL 系统
            sudo yum install -y python3
        else
            echo -e "${RED}无法确定系统类型，请手动安装 Python3${NC}"
            exit 1
        fi
    fi
    
    # 检查并安装 pip3
    if ! command -v pip3 &> /dev/null; then
        echo -e "${YELLOW}未检测到 pip3，正在尝试安装...${NC}"
        if [ -f /etc/debian_version ]; then
            # Debian/Ubuntu 系统
            sudo apt-get update && sudo apt-get install -y python3-pip
        elif [ -f /etc/redhat-release ]; then
            # CentOS/RHEL 系统
            sudo yum install -y python3-pip
        else
            echo -e "${RED}无法确定系统类型，请手动安装 pip3${NC}"
            exit 1
        fi
    fi
    
    # 再次检查是否安装成功
    if command -v python3 &> /dev/null && command -v pip3 &> /dev/null; then
        echo -e "${GREEN}环境检查通过${NC}"
    else
        echo -e "${RED}环境检查失败，请手动安装 Python3 和 pip3${NC}"
        exit 1
    fi
}

# 安装依赖函数
install_dependencies() {
    echo -e "${YELLOW}正在安装依赖...${NC}"
    
    # 确保 requirements.txt 存在
    if [ ! -f "$BOT_DIR/requirements.txt" ]; then
        echo -e "${RED}未找到 requirements.txt 文件${NC}"
        exit 1
    fi
    
    # 安装依赖
    pip3 install -r "$BOT_DIR/requirements.txt"
    
    echo -e "${GREEN}依赖安装完成${NC}"
}

# 配置引导函数
configure_bot() {
    echo -e "${YELLOW}开始配置 Bot...${NC}"
    
    # 检查配置文件是否存在
    if [ ! -f "$BOT_DIR/config.yml" ]; then
        if [ -f "$BOT_DIR/config.yml.example" ]; then
            cp "$BOT_DIR/config.yml.example" "$BOT_DIR/config.yml"
            echo -e "${GREEN}已从示例文件创建配置文件${NC}"
        else
            echo -e "${RED}未找到配置文件模板${NC}"
            exit 1
        fi
    fi
    
    # 提示用户编辑配置文件
    echo -e "${YELLOW}请编辑 $BOT_DIR/config.yml 文件，填入必要的配置信息${NC}"
    read -p "按回车键继续..."
    nano "$BOT_DIR/config.yml"
}

# 安装函数
install() {
    echo -e "${YELLOW}开始安装 Telegram Bot...${NC}"
    
    check_environment
    install_dependencies
    configure_bot
    
    # 创建服务文件
    cat > /etc/systemd/system/$SERVICE_NAME <<EOL
[Unit]
Description=Telegram Bot Service
After=network.target

[Service]
ExecStart=/usr/bin/python3 $BOT_DIR/bot.py
WorkingDirectory=$BOT_DIR
StandardOutput=inherit
StandardError=inherit
Restart=always
User=root

[Install]
WantedBy=multi-user.target
EOL

    # 重新加载systemd
    systemctl daemon-reload

    # 启用服务
    systemctl enable $SERVICE_NAME

    # 启动服务
    systemctl start $SERVICE_NAME

    # 创建符号链接
    create_symlink

    echo -e "${GREEN}安装完成并已启动服务${NC}"
}

# 重启服务函数
restart() {
    echo -e "${YELLOW}正在重启 Bot 服务...${NC}"
    sudo systemctl daemon-reload
    sudo systemctl restart $SERVICE_NAME
    
    # 等待服务重启完成
    while ! systemctl is-active --quiet $SERVICE_NAME; do
        sleep 1
    done
    
    echo -e "${GREEN}重启完成${NC}"
    check_status
}

# 停止服务函数
stop() {
    echo -e "${YELLOW}正在停止 Bot 服务...${NC}"
    sudo systemctl stop $SERVICE_NAME
    echo -e "${GREEN}已停止服务${NC}"
}

# 检查状态函数
check_status() {
    if systemctl is-active --quiet $SERVICE_NAME; then
        echo -e "运行状态：${GREEN}已运行${NC}"
    else
        echo -e "运行状态：${RED}未运行${NC}"
    fi
}

# 查看日志函数
view_logs() {
    echo -e "${YELLOW}正在查看 Bot 日志...${NC}"
    journalctl -u $SERVICE_NAME -n 50 --no-pager
}

# 主菜单
show_menu() {
    clear
    echo "================================"
    echo "    Telegram Bot 管理菜单"
    echo "================================"
    echo "1. 安装 Bot 服务"
    echo "2. 重启 Bot 服务"
    echo "3. 停止 Bot 服务"
    echo "4. 查看 Bot 日志"
    echo "5. 退出"
    echo "================================"
    check_status
    echo "================================"
}

# 主循环
while true; do
    show_menu
    read -p "请选择操作 [1-5]: " choice
    case $choice in
        1)
            install
            ;;
        2)
            restart
            ;;
        3)
            stop
            ;;
        4)
            view_logs
            ;;
        5)
            echo -e "${GREEN}感谢使用，再见！${NC}"
            exit 0
            ;;
        *)
            echo -e "${RED}无效选项，请重新选择${NC}"
            ;;
    esac
    read -p "按回车键继续..."
done
