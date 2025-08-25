FROM python:3.10-slim


COPY requirements.txt .

RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.4.0 torchvision==0.19.0 torchaudio==2.4.0

RUN pip install --no-cache-dir --upgrade pip \
&& pip install --no-cache-dir -r requirements.txt

# 필요 도구 설치
RUN apt-get update && apt-get install -y wget unzip ca-certificates && rm -rf /var/lib/apt/lists/*

# Sonar Scanner 설치
ENV SONAR_SCANNER_VERSION=5.0.1.3006
RUN wget -q https://binaries.sonarsource.com/Distribution/sonar-scanner-cli/sonar-scanner-cli-${SONAR_SCANNER_VERSION}-linux.zip \
 && unzip sonar-scanner-cli-${SONAR_SCANNER_VERSION}-linux.zip \
 && rm sonar-scanner-cli-${SONAR_SCANNER_VERSION}-linux.zip \
 && mv sonar-scanner-${SONAR_SCANNER_VERSION}-linux /opt/sonar-scanner
# PATH 등록
ENV PATH="/opt/sonar-scanner/bin:${PATH}"

COPY app ./ai/security/app

WORKDIR /ai

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=UTF-8

# 실행
CMD ["python", "-m", "security.app.main"]
