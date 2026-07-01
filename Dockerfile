FROM python:3.11-slim

# 安装 ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt flask

# 复制项目文件
COPY . .

# 创建输出目录
RUN mkdir -p output/episodes output/scripts output/analyses

EXPOSE 5000

CMD ["python", "dashboard.py"]
