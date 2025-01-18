#!/bin/bash

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 服务名称
SERVICE_NAME="bot.service"

# 获取脚本所在目录
BOT_DIR="$( cd "$( dirname "$(readlink -f "${BASH_SOURCE[0]}")" )" &> /dev/null && pwd )"

# 脚本名称
SCRIPT_NAME=$(basename "$0")

# 检查是否以root权限运行
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}请以root权限运行此脚本${NC}"
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

    sudo apt install python3-venv
    
    # 确保 requirements.txt 存在
    if [ ! -f "$BOT_DIR/requirements.txt" ]; then
        echo -e "${RED}未找到 requirements.txt 文件${NC}"
        exit 1
    fi

    # 创建虚拟环境
    python3 -m venv "$BOT_DIR/venv"
    
    # 激活虚拟环境
    source "$BOT_DIR/venv/bin/activate"
    
    # 安装依赖
    pip install -r "$BOT_DIR/requirements.txt"
    
    echo -e "${GREEN}依赖安装完成${NC}"
}

# 卸载函数
uninstall() {
    echo -e "${YELLOW}正在卸载 Telegram Bot...${NC}"
    
    # 停止服务
    sudo systemctl stop $SERVICE_NAME
    
    # 禁用服务
    sudo systemctl disable $SERVICE_NAME
    
    # 删除服务文件
    sudo rm /etc/systemd/system/$SERVICE_NAME
    
    # 重新加载systemd
    sudo systemctl daemon-reload
    
    # 提示用户是否要删除Bot目录
    read -p "是否删除Bot目录 ($BOT_DIR)? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf $BOT_DIR
        echo -e "${GREEN}Bot目录已删除${NC}"
    else
        echo -e "${YELLOW}Bot目录未删除${NC}"
    fi
    
    echo -e "${GREEN}卸载完成${NC}"
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
    read -p "请修改本目录（$BOT_DIR）的config.yml后，按回车键继续..."
}

# 添加计划任务函数
add_cron_job() {
    echo -e "${YELLOW}正在添加计划任务...${NC}"
    
    # 创建包含所有命令的 cron 任务
    CRON_CMD="30 3 * * * systemctl daemon-reload; systemctl kill -s SIGKILL bot.service 2>/dev/null; sleep 0.5; systemctl start bot.service"
    
    # 添加到 crontab
    (crontab -l 2>/dev/null | grep -v "bot.service"; echo "$CRON_CMD") | crontab -
    
    echo -e "${GREEN}计划任务已添加，每天 3:30 快速重启 Bot 服务${NC}"
}

# 安装函数
install() {
    echo -e "${YELLOW}开始安装 Telegram Bot...${NC}"

    sudo timedatectl set-timezone Asia/Shanghai
    check_environment
    install_dependencies
    configure_bot
    
    # 创建服务文件
    cat > /etc/systemd/system/$SERVICE_NAME <<EOL
[Unit]
Description=Telegram Bot Service
After=network.target

[Service]
ExecStart=$BOT_DIR/venv/bin/python $BOT_DIR/bot.py
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

    # 添加计划任务
    add_cron_job

    echo -e "${GREEN}安装完成并已启动服务${NC}"
}

# 添加一个等待服务状态的函数，带超时机制
wait_for_service_status() {
    local desired_status=$1  # "active" 或 "inactive"
    local timeout=10         # 最大等待秒数
    local counter=0
    
    while [ $counter -lt $timeout ]; do
        if [ "$desired_status" = "active" ]; then
            systemctl is-active --quiet bot.service && return 0
        else
            ! systemctl is-active --quiet bot.service && return 0
        fi
        sleep 0.5
        counter=$((counter + 1))
    done
    return 1  # 超时
}

# 优化后的启动函数
start() {
    if systemctl is-active --quiet bot.service; then
        echo -e "${YELLOW}Bot 已经在运行中。${NC}"
        return
    fi
    
    echo -e "${YELLOW}正在启动 Bot 服务...${NC}"
    systemctl daemon-reload
    systemctl start bot.service
    
    if wait_for_service_status "active"; then
        echo -e "${GREEN}Bot 已成功启动！${NC}"
    else
        echo -e "${RED}Bot 启动超时，请检查日志文件。${NC}"
    fi
}

# 优化后的重启函数
restart() {
    echo -e "${YELLOW}正在重启 Bot 服务...${NC}"
    
    # 先重新加载 systemd 配置
    systemctl daemon-reload
    
    # 直接使用 SIGKILL 强制结束进程
    systemctl kill -s SIGKILL bot.service 2>/dev/null
    
    # 短暂等待确保进程已经结束
    sleep 0.5
    
    # 启动服务
    systemctl start bot.service
    
    # 使用更短的超时检查
    if wait_for_service_status "active"; then
        echo -e "${GREEN}Bot 已成功重启！${NC}"
    else
        echo -e "${RED}Bot 启动失败，请检查日志文件。${NC}"
    fi
}

# 优化后的停止函数
stop() {
    if ! systemctl is-active --quiet bot.service; then
        echo -e "${YELLOW}Bot 服务未在运行。${NC}"
        return
    fi
    
    echo -e "${YELLOW}正在停止 Bot 服务...${NC}"
    systemctl stop bot.service
    
    if wait_for_service_status "inactive"; then
        echo -e "${GREEN}Bot 服务已停止。${NC}"
    else
        echo -e "${RED}服务停止超时，尝试强制停止...${NC}"
        systemctl kill -s SIGKILL bot.service
        sleep 1
        if wait_for_service_status "inactive"; then
            echo -e "${GREEN}强制停止成功！${NC}"
        else
            echo -e "${RED}强制停止失败，请手动检查服务状态。${NC}"
        fi
    fi
}

# 检查状态函数
check_status() {
    if systemctl is-active --quiet bot.service; then
        echo -e "运行状态：${GREEN}已运行${NC}"
    else
        echo -e "运行状态：${RED}未运行${NC}"
    fi
}

# 查看日志函数
view_logs() {
    echo -e "${YELLOW}正在查看 Bot 日志...${NC}"
    # 使用 tail -f 实时查看日志
    sudo journalctl -u $SERVICE_NAME -n 30 -f
}

# 配置文件更新函数
update_config() {
    local example_file="$1"
    local current_file="$2"
    
    echo -e "${YELLOW}正在检查配置文件更新...${NC}"
    
    # 使用 yq 工具处理 YAML 文件
    if ! command -v yq &> /dev/null; then
        echo -e "${YELLOW}正在安装 yq 工具...${NC}"
        wget https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64 -O /usr/local/bin/yq
        chmod +x /usr/local/bin/yq
    fi
    
    # 读取示例配置中的所有键
    while IFS= read -r key; do
        # 检查当前配置是否缺少该键
        if ! yq eval ".$key" "$current_file" &>/dev/null; then
            echo -e "${YELLOW}检测到新的配置项: $key${NC}"
            # 获取示例配置中的默认值
            default_value=$(yq eval ".$key" "$example_file")
            echo -e "请输入 $key 的值 (直接回车使用默认值):"
            echo -e "默认值: $default_value"
            read -r new_value
            
            if [ -z "$new_value" ]; then
                new_value="$default_value"
            fi
            
            # 添加新配置到当前配置文件
            echo -e "\n# Added by update script\n$key: $new_value" >> "$current_file"
            echo -e "${GREEN}已添加配置项: $key${NC}"
        fi
    done < <(yq eval 'keys | .[]' "$example_file")
}

# 更新函数
update() {
    echo -e "${YELLOW}正在更新 Telegram Bot...${NC}"
    
    # 进入目标目录
    cd "$BOT_DIR" || exit
    
    # 备份当前配置
    cp config.yml config.yml.bak
    
    # 拉取特定文件
    git fetch origin main
    git checkout origin/main -- bot.py handler.py location_names.py requirements.txt config.yml.example
    
    # 更新配置文件
    update_config "config.yml.example" "config.yml"
    
    echo -e "${GREEN}拉取更新成功${NC}"
    echo -e "${YELLOW}正在重启应用bot......${NC}"
    
    # 重启服务
    systemctl daemon-reload
    systemctl kill -s SIGKILL bot.service 2>/dev/null
    sleep 0.5
    systemctl start bot.service
    
    if wait_for_service_status "active"; then
        echo -e "${GREEN}Bot 已成功重启！${NC}"
    else
        echo -e "${RED}Bot 启动失败，请检查日志文件。${NC}"
    fi
    
    echo -e "${GREEN}更新完成${NC}"
}

# 添加进程状态检查函数
is_running() {
    pgrep -f "python3.*bot.py" >/dev/null
    return $?
}

# 主菜单
show_menu() {
    echo "============================================"
    echo "    Crisp for Telegram Bot 管理菜单"
    echo "============================================"
    echo ""
    echo "1. 安装 crispBot"
    echo ""
    echo "2. 启动 Bot "
    echo ""
    echo "3. 重启 Bot "
    echo ""
    echo "4. 停止 Bot "
    echo ""
    echo "5. 查看 Bot 日志"
    echo ""
    echo "6. 卸载 crispBot"
    echo ""
    echo "7. 更新 crispBot"
    echo ""
    echo "0. 退出脚本"
    echo ""
    echo "============================================"
    check_status
    echo "============================================"
    echo "若config.yml配置没有填写,状态也会为显示"已运行""
    echo "安装完成后请自行测试功能是否正常"
    echo "你可以随时使用crispbot唤起本菜单"
    echo "============================================"
}

# 主循环
while true; do
    show_menu
    echo -e "${YELLOW}请选择操作 [1-6]: ${NC}"
    read -n 1 -s choice
    echo  # 打印一个换行
    case $choice in
        1)
            install
            ;;
        2)
            start
            ;;
        3)
            restart
            ;;
        4)
            stop
            ;;
        5)
            view_logs
            echo -e "${YELLOW}按任意键返回主菜单...${NC}"
            read -n 1 -s
            ;;
        6)
            uninstall
            ;;
        7)
            update
            ;;
        0)
            echo -e "${GREEN}感谢使用，再见！${NC}"
            exit 0
            ;;
        *)
            echo -e "${RED}无效选项，请重新选择${NC}"
            sleep 2
            ;;
    esac
done
