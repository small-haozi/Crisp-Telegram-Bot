#!/bin/bash

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查是否安装了Docker和Docker Compose
check_docker() {
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}Docker未安装，正在安装...${NC}"
        curl -fsSL https://get.docker.com | sh
        systemctl start docker
        systemctl enable docker
    fi

    if ! command -v docker-compose &> /dev/null; then
        echo -e "${RED}Docker Compose未安装，正在安装...${NC}"
        curl -L "https://github.com/docker/compose/releases/download/v2.24.5/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
        chmod +x /usr/local/bin/docker-compose
    fi
}

# 创建新的bot实例
create_bot() {
    echo -e "${YELLOW}请输入新bot的编号（例如：3）：${NC}"
    read bot_number
    
    echo -e "${YELLOW}请输入bot的别名（例如：us-bot）：${NC}"
    read bot_alias
    
    # 复制配置文件
    cp config.yml.example "config${bot_number}-${bot_alias}.yml"
    mkdir -p "data${bot_number}"
    # 创建空的session_mapping文件
    touch "session_mapping${bot_number}-${bot_alias}.yml"
    # 设置适当的权限
    chmod 666 "session_mapping${bot_number}-${bot_alias}.yml"
    
    echo -e "${GREEN}已创建配置文件 config${bot_number}-${bot_alias}.yml${NC}"
    echo -e "${YELLOW}请编辑配置文件后再启动服务${NC}"
    
    # 添加到docker-compose.yml
    cat >> docker-compose.yml <<EOL

  bot${bot_number}:
    build: .
    container_name: crisp_bot_${bot_number}_${bot_alias}
    restart: always
    volumes:
      - ./config${bot_number}-${bot_alias}.yml:/app/config.yml
      - ./data${bot_number}:/app/data
      - ./session_mapping${bot_number}-${bot_alias}.yml:/app/session_mapping.yml
    environment:
      - TZ=Asia/Shanghai
EOL
}

# 启动所有bot
start_all() {
    docker-compose up -d
    echo -e "${GREEN}所有bot已启动${NC}"
}

# 停止所有bot
stop_all() {
    docker-compose down
    echo -e "${GREEN}所有bot已停止${NC}"
}

# 停止指定bot
stop_bot() {
    echo -e "${YELLOW}请输入要停止的bot编号：${NC}"
    read bot_number
    docker-compose stop "bot${bot_number}"
    echo -e "${GREEN}Bot ${bot_number} 已停止${NC}"
}

# 重启指定bot
restart_bot() {
    echo -e "${YELLOW}请输入要重启的bot编号：${NC}"
    read bot_number
    docker-compose restart "bot${bot_number}"
    echo -e "${GREEN}Bot ${bot_number} 已重启${NC}"
}

# 查看日志
view_logs() {
    echo -e "${YELLOW}请输入要查看日志的bot编号（输入0查看所有）：${NC}"
    read bot_number
    if [ "$bot_number" = "0" ]; then
        docker-compose logs -f
    else
        docker-compose logs -f "bot${bot_number}"
    fi
}

# 更新bot
update_bot() {
    echo -e "${YELLOW}正在更新Bot...${NC}"
    
    # 保存当前目录
    current_dir=$(pwd)
    
    # 拉取最新代码
    git pull
    
    if [ $? -eq 0 ]; then
        # 重新构建所有容器
        docker-compose build
        
        echo -e "${YELLOW}是否要重启所有Bot实例？[y/N]${NC}"
        read restart_choice
        if [[ $restart_choice =~ ^[Yy]$ ]]; then
            docker-compose up -d
            echo -e "${GREEN}所有Bot已更新并重启${NC}"
        else
            echo -e "${YELLOW}Bot已更新，但未重启。请在需要时手动重启。${NC}"
        fi
    else
        echo -e "${RED}更新失败，请检查网络连接或代码仓库状态${NC}"
    fi
}

# 主菜单
show_menu() {
    echo "===================================="
    echo "    Crisp Telegram Bot 管理面板"
    echo "===================================="
    echo "1. 创建新的bot实例"
    echo "2. 启动所有bot"
    echo "3. 停止所有bot"
    echo "4. 停止指定bot"
    echo "5. 重启指定bot"
    echo "6. 查看bot日志"
    echo "7. 更新Bot"
    echo "0. 退出"
    echo "===================================="
}

# 主程序
main() {
    check_docker
    
    while true; do
        show_menu
        read -p "请选择操作 [0-7]: " choice
        case $choice in
            1) create_bot ;;
            2) start_all ;;
            3) stop_all ;;
            4) stop_bot ;;
            5) restart_bot ;;
            6) view_logs ;;
            7) update_bot ;;
            0) exit 0 ;;
            *) echo -e "${RED}无效的选择${NC}" ;;
        esac
        echo
        read -p "按回车键继续..."
    done
}

main 
