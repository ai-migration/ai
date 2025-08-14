# scripts/test_env.py

from dotenv import load_dotenv
import os

#버전 변환을 하기 위해서는 github 토큰 필요

load_dotenv()  # .env 파일 로드

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
print("✅ GITHUB_TOKEN 불러옴:", GITHUB_TOKEN is not None)
print("🔑 GITHUB_TOKEN 값:", GITHUB_TOKEN)
