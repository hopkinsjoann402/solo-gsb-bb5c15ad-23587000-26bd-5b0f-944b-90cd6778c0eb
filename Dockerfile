FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/tides.db \
    HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app

# 先装依赖, 利用层缓存
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 再拷代码
COPY app ./app
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh && mkdir -p /data

# 以非 root 用户运行, 确保数据目录可写
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /data /app
USER appuser

EXPOSE 8000

# 健康检查直接打 /health
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=5 \
    CMD python3 -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8000')).read()" || exit 1

ENTRYPOINT ["./entrypoint.sh"]
