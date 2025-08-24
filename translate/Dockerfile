FROM python:3.10-slim


COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
&& pip install --no-cache-dir -r requirements.txt

RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.4.0 torchvision==0.19.0 torchaudio==2.4.0

COPY app ./ai/translate/app

WORKDIR /ai

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=UTF-8

# 실행
CMD ["python", "-m", "translate.app.main"]
