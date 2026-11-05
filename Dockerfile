FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 先拷依赖清单单独装，利用 Docker 层缓存：源码改动不会重装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 再拷全部源码（根目录：main.py / server.py / graph / models / tools）
COPY . .

EXPOSE 8000

# FastAPI 实例在 server.py 的 app 对象
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
