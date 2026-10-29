FROM python:3.12-slim

WORKDIR /app
COPY danmaku_bridge ./danmaku_bridge

# 只读挂载媒体目录，:ro 也可以（字幕需要写在媒体目录旁，故默认读写）
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "-m", "danmaku_bridge"]
CMD ["--help"]
