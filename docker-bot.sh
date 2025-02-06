#!/bin/bash

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查是否安装了sudo
check_sudo() {
    if ! command -v sudo &> /dev/null; then
        echo -e "${RED}sudo未安装，正在安装...${NC}"
        # 使用su切换到root用户安装sudo
        su -c "apt-get update && apt-get install -y sudo"
        if [ $? -ne 0 ]; then
            echo -e "${RED}安装sudo失败，请手动安装后再运行此脚本${NC}"
            exit 1
        fi
    fi
    
    # 检查当前用户是否在sudo组中
    if ! groups | grep -q '\bsudo\b'; then
        echo -e "${YELLOW}当前用户不在sudo组中，尝试添加...${NC}"
        su -c "usermod -aG sudo $USER"
        if [ $? -ne 0 ]; then
            echo -e "${RED}添加用户到sudo组失败，请手动配置sudo权限${NC}"
            exit 1
        fi
        echo -e "${GREEN}已添加当前用户到sudo组，请重新登录后再运行此脚本${NC}"
        exit 1
    fi
}

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

# 检查是否安装了zip
check_zip() {
    if ! command -v zip &> /dev/null; then
        echo -e "${RED}zip未安装，正在安装...${NC}"
        sudo apt-get update && sudo apt-get install -y zip
    fi
}

# 保存映射关系的文件
MAPPING_FILE="/opt/crisp_bot/instance_mapping.txt"

# 显示所有实例信息
show_instances() {
    echo -e "${YELLOW}当前所有Bot实例：${NC}"
    if [ -f "$MAPPING_FILE" ]; then
        echo -e "\n编号\t别名\t\t状态"
        echo "--------------------------------"
        while IFS=: read -r number alias; do
            # 检查容器状态
            status=$(docker-compose ps --status running "bot${number}" 2>/dev/null | grep -v "Name" | wc -l)
            if [ "$status" -eq 1 ]; then
                status_text="${GREEN}运行中${NC}"
            else
                status_text="${RED}已停止${NC}"
            fi
            echo -e "${number}\t${alias}\t\t${status_text}"
        done < "$MAPPING_FILE"
        echo "--------------------------------"
    else
        echo -e "${YELLOW}暂无Bot实例${NC}"
    fi
    echo
}

# 卸载或迁移bot
uninstall_or_migrate() {
    echo -e "${YELLOW}请选择操作：${NC}"
    echo -e "1. 卸载Bot"
    echo -e "2. 迁移备份"
    echo -e "0. 返回"
    read -p "请选择 [0-2]: " operation

    case $operation in
        1)
            echo -e "${YELLOW}警告：这将删除所有bot实例和相关数据！${NC}"
            echo -e "${YELLOW}请输入 'YES' 确认卸载：${NC}"
            read confirm
            
            if [ "$confirm" = "YES" ]; then
                # 停止并删除所有容器
                docker-compose down
                
                # 删除所有相关文件
                rm -f docker-compose.yml
                # 询问是否删除配置文件
                echo -e "${YELLOW}是否删除所有配置文件和数据？[y/N]${NC}"
                read delete_data
                if [[ $delete_data =~ ^[Yy]$ ]]; then
                    # 获取当前时间作为备份文件名
                    backup_time=$(date +"%Y%m%d_%H%M%S")
                    backup_file="crisp_bot_backup_${backup_time}.zip"
                    
                    # 创建备份
                    echo -e "${YELLOW}正在创建备份...${NC}"
                    if sudo zip -r "$backup_file" /opt/crisp_bot/ > /dev/null 2>&1; then
                        echo -e "${GREEN}备份已保存为: ${backup_file}${NC}"
                    else
                        echo -e "${RED}备份创建失败${NC}"
                        echo -e "${YELLOW}是否继续删除？[y/N]${NC}"
                        read continue_delete
                        if [[ ! $continue_delete =~ ^[Yy]$ ]]; then
                            echo -e "${YELLOW}取消卸载${NC}"
                            return 1
                        fi
                    fi
                    
                    sudo rm -rf /opt/crisp_bot
                    echo -e "${GREEN}已删除所有配置文件和数据${NC}"
                fi
                
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
            ;;
        2)
            # 创建迁移备份
            backup_time=$(date +"%Y%m%d_%H%M%S")
            backup_file="crisp_bot_backup_${backup_time}.zip"
            
            echo -e "${YELLOW}正在创建迁移备份...${NC}"
            if sudo zip -r "$backup_file" /opt/crisp_bot/ > /dev/null 2>&1; then
                echo -e "${GREEN}迁移备份已保存为: ${backup_file}${NC}"
                echo -e "${YELLOW}请将此文件复制到新服务器上使用${NC}"
            else
                echo -e "${RED}创建迁移备份失败${NC}"
            fi
            ;;
        0)
            return 0
            ;;
        *)
            echo -e "${RED}无效的选择${NC}"
            ;;
    esac
}

# 创建新的bot实例
create_bot() {
    # 检查目录是否已存在
    if [ -d "/opt/crisp_bot" ]; then
        echo -e "${YELLOW}检测到已存在的crisp_bot目录${NC}"
        echo -e "1. 继续使用现有目录"
        echo -e "2. 备份并创建新目录"
        echo -e "0. 取消"
        read -p "请选择 [0-2]: " dir_choice
        
        case $dir_choice in
            1)
                echo -e "${YELLOW}将在现有目录中创建新实例${NC}"
                ;;
            2)
                backup_time=$(date +"%Y%m%d_%H%M%S")
                backup_dir="/opt/crisp_bot_backup_${backup_time}"
                echo -e "${YELLOW}正在备份现有目录到 ${backup_dir}${NC}"
                sudo mv /opt/crisp_bot "$backup_dir"
                ;;
            *)
                echo -e "${YELLOW}操作已取消${NC}"
                return 1
                ;;
        esac
    fi
    
    echo -e "${YELLOW}请输入新bot的编号（例如：3）：${NC}"
    read bot_number
    
    # 检查是否已存在相同编号的bot
    if grep -q "bot${bot_number}:" docker-compose.yml; then
        echo -e "${RED}编号 ${bot_number} 的bot已存在，请使用其他编号${NC}"
        return 1
    fi
    
    echo -e "${YELLOW}请输入bot的别名（例如：us-bot）：${NC}"
    read bot_alias
    
    # 保存编号和别名的映射关系
    sudo mkdir -p "$(dirname "$MAPPING_FILE")"
    echo "${bot_number}:${bot_alias}" | sudo tee -a "$MAPPING_FILE" > /dev/null

    # 在 /opt 下创建独立文件夹
    sudo mkdir -p "/opt/crisp_bot/${bot_alias}"
    
    # 复制配置文件
    sudo cp config.yml.example "/opt/crisp_bot/${bot_alias}/config.yml"
    sudo mkdir -p "/opt/crisp_bot/${bot_alias}/data"
    # 创建空的session_mapping文件
    sudo touch "/opt/crisp_bot/${bot_alias}/session_mapping.yml"
    # 设置适当的权限
    sudo chmod -R 777 "/opt/crisp_bot/${bot_alias}"
    
    echo -e "${GREEN}已在 /opt/crisp_bot/${bot_alias} 创建配置文件${NC}"
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
      - /opt/crisp_bot/${bot_alias}/config.yml:/app/config.yml
      - /opt/crisp_bot/${bot_alias}/data:/app/data
      - /opt/crisp_bot/${bot_alias}/session_mapping.yml:/app/session_mapping.yml
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
    show_instances
    echo -e "${YELLOW}请输入要停止的bot编号：${NC}"
    read bot_number
    docker-compose stop "bot${bot_number}"
    echo -e "${GREEN}Bot ${bot_number} 已停止${NC}"
}

# 重启指定bot
restart_bot() {
    show_instances
    echo -e "${YELLOW}请输入要重启的bot编号：${NC}"
    read bot_number
    docker-compose restart "bot${bot_number}"
    echo -e "${GREEN}Bot ${bot_number} 已重启${NC}"
}

# 查看日志
view_logs() {
    show_instances
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

# 主菜单
show_menu() {
    echo "===================================="
    echo "    Crisp Telegram Bot 管理面板"
    echo "===================================="
    show_instances
    echo ""
    echo "1. 创建新的bot实例"
    echo ""
    echo "2. 启动所有bot"
    echo ""
    echo "3. 停止所有bot"
    echo ""
    echo "4. 停止指定bot"
    echo ""
    echo "5. 重启指定bot"
    echo ""
    echo "6. 查看bot日志"
    echo ""
    echo "7. 更新Bot"
    echo ""
    echo "8. 卸载或迁移"
    echo ""
    echo "0. 退出"
    echo "===================================="
}

# 主程序
main() {
    check_sudo
    check_docker
    check_zip
    
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
            8) uninstall_or_migrate ;;
            0) exit 0 ;;
            *) echo -e "${RED}无效的选择${NC}" ;;
        esac
        echo
        read -p "按回车键继续..."
    done
}

main 
