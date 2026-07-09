FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Singapore

WORKDIR /app

# 先装依赖，利用 Docker 层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p data output

# 默认常驻定时模式；GitHub Actions 会以 RUN_MODE=once 覆盖。
# 具体每日时刻在 config.yaml 的 settings.schedules 配置（北京/纽约 09:20）。
ENV RUN_MODE=schedule \
    RUN_ON_START=false

CMD ["python", "run.py"]
