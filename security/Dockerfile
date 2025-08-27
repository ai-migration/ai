FROM python:3.10-slim


COPY requirements.txt .

RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.4.0 torchvision==0.19.0 torchaudio==2.4.0

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# 필요 도구 및 Java 설치
RUN apt-get update && apt-get install -y wget unzip ca-certificates openjdk-21-jdk \
    && rm -rf /var/lib/apt/lists/*
# RUN apt-get update && apt-get install -y wget unzip ca-certificates openjdk-17-jdk \
#     && rm -rf /var/lib/apt/lists/*

# JAVA_HOME 설정
ENV JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
ENV PATH="${JAVA_HOME}/bin:${PATH}"

# Sonar Scanner 설치
ARG SONAR_SCANNER_VERSION=7.1.0.4889
ENV SONAR_SCANNER_VERSION=${SONAR_SCANNER_VERSION}

RUN wget https://binaries.sonarsource.com/Distribution/sonar-scanner-cli/sonar-scanner-cli-${SONAR_SCANNER_VERSION}.zip -O sonar-scanner.zip \
    && unzip sonar-scanner.zip \
    && rm sonar-scanner.zip \
    && mv sonar-scanner-${SONAR_SCANNER_VERSION} /opt/sonar-scanner

ENV PATH="/opt/sonar-scanner/bin:${PATH}"

# 앱 복사
COPY app ./ai/security/app

WORKDIR /ai

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=UTF-8

# 실행
CMD ["python", "-m", "security.app.main"]