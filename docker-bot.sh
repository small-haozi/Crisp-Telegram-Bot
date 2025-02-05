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
    
    # 检查是否已存在相同编号的bot
    if grep -q "bot${bot_number}:" docker-compose.yml; then
        echo -e "${RED}编号 ${bot_number} 的bot已存在，请使用其他编号${NC}"
        return 1
    fi
    
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
    
    # 检查docker-compose.yml是否以换行符结尾
    if [ -f docker-compose.yml ] && [ -s docker-compose.yml ]; then
        last_char=$(tail -c1 docker-compose.yml)
        if [ "$last_char" != "" ]; then
            echo "" >> docker-compose.yml
        fi
    fi
    
    # 添加到docker-compose.yml
    cat >> docker-compose.yml <<EOL

  bot${bot_number}:
    build: .
    container_name: crisp_bot_${bot_number}_${bot_alias}
    restart: unless-stopped
    volumes:
      - ./config${bot_number}-${bot_alias}.yml:/app/config.yml
      - ./data${bot_number}:/app/data
      - ./session_mapping${bot_number}-${bot_alias}.yml:/app/session_mapping.yml
    environment:
      - TZ=Asia/Shanghai
EOL

    echo -e "${GREEN}已将 bot${bot_number} 添加到 docker-compose.yml${NC}"
    
    echo -e "${YELLOW}是否要立即构建并启动新的bot实例？[Y/n]${NC}"
    read start_choice
    if [[ ! $start_choice =~ ^[Nn]$ ]]; then
        docker-compose up -d "bot${bot_number}"
        echo -e "${GREEN}Bot ${bot_number} 已启动${NC}"
    else
        echo -e "${YELLOW}Bot ${bot_number} 已创建但未启动，您可以稍后使用选项2或在编辑配置后再启动${NC}"
    fi
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
    
    # 检查是否有本地修改
    if [ -n "$(git status --porcelain)" ]; then
        echo -e "${YELLOW}检测到本地文件有修改。${NC}"
        echo -e "${YELLOW}1. 保存本地修改（stash）${NC}"
        echo -e "${YELLOW}2. 放弃本地修改${NC}"
        echo -e "${YELLOW}3. 取消更新${NC}"
        read -p "请选择操作 [1-3]: " stash_choice
        
        case $stash_choice in
            1)
                git stash
                echo -e "${GREEN}已保存本地修改${NC}"
                ;;
            2)
                git checkout -- .
                echo -e "${GREEN}已放弃本地修改${NC}"
                ;;
            3)
                echo -e "${YELLOW}取消更新${NC}"
                return 1
                ;;
            *)
                echo -e "${RED}无效的选择${NC}"
                return 1
                ;;
        esac
    fi
    
    # 拉取最新代码
    git pull
    
    if [ $? -eq 0 ]; then
        # 如果之前有保存的修改，尝试恢复
        if [ "$stash_choice" = "1" ]; then
            if git stash pop; then
                echo -e "${GREEN}已恢复本地修改${NC}"
            else
                echo -e "${RED}恢复本地修改时发生冲突，请手动解决${NC}"
                return 1
            fi
        fi
    
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

# 卸载bot
uninstall_bot() {
    echo -e "${YELLOW}警告：这将删除所有bot实例和相关数据！${NC}"
    echo -e "${YELLOW}请输入 'YES' 确认卸载：${NC}"
    read confirm
    
    if [ "$confirm" = "YES" ]; then
        # 停止并删除所有容器
        docker-compose down
        
        # 删除所有相关文件
        rm -f docker-compose.yml
        rm -f config*-*.yml
        rm -f session_mapping*-*.yml
        rm -rf data*/
        
        # 删除Docker镜像
        docker rmi $(docker images | grep "crisp_bot" | awk '{print $3}') 2>/dev/null
        
        echo -e "${GREEN}已完全卸载所有bot实例和相关数据${NC}"
        echo -e "${YELLOW}配置文件模板（config.yml.example）和脚本文件已保留${NC}"
        
        # 询问是否退出脚本
        echo -e "${YELLOW}是否要退出管理脚本？[Y/n]${NC}"
        read exit_choice
        if [[ $exit_choice =~ ^[Nn]$ ]]; then
            return 0
        else
            exit 0
        fi
    else
        echo -e "${YELLOW}取消卸载${NC}"
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
    echo "8. 卸载Bot"
    echo "0. 退出"
    echo "===================================="
}

# 主程序
main() {
    check_docker
    
    # 检查 docker-compose.yml 是否存在
    if [ ! -f docker-compose.yml ]; then
        if [ -f docker-compose.yml.example ]; then
            cp docker-compose.yml.example docker-compose.yml
            echo -e "${GREEN}已创建 docker-compose.yml${NC}"
        else
            echo "version: '3'" > docker-compose.yml
            echo "" >> docker-compose.yml
            echo "services:" >> docker-compose.yml
            echo -e "${GREEN}已创建空的 docker-compose.yml${NC}"
        fi
    fi
    
    while true; do
        show_menu
        read -p "请选择操作 [0-8]: " choice
        case $choice in
            1) create_bot ;;
            2) start_all ;;
            3) stop_all ;;
            4) stop_bot ;;
            5) restart_bot ;;
            6) view_logs ;;
            7) update_bot ;;
            8) uninstall_bot ;;
            0) exit 0 ;;
            *) echo -e "${RED}无效的选择${NC}" ;;
        esac
        echo
        read -p "按回车键继续..."
    done
}

main 
