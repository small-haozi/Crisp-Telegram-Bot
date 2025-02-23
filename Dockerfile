FROM python:3.9-slim

WORKDIR /app

# 安装必要的系统依赖
RUN apt-get update && apt-get install -y \
    git \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 复制项目文件
COPY requirements.txt .
COPY bot.py .
COPY handler.py .
COPY location_names.py .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 设置时区
ENV TZ=Asia/Shanghai
# 添加 Docker 环境标识
ENV DOCKER_CONTAINER=true

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 创建session_mapping.yml并设置权限
RUN touch session_mapping.yml && \
    chmod 666 session_mapping.yml

CMD ["python", "bot.py"] 
