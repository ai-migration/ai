FROM python:3.10-slim


COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
&& pip install --no-cache-dir -r requirements.txt

COPY app ./ai/security/app

WORKDIR /ai

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=UTF-8

# 실행
CMD ["python", "-m", "security.app.main"]
