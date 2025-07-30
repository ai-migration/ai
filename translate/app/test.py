# test_transform.py
import os
from dotenv import load_dotenv
from translate.app.transformer import run_pipeline_with_rag

# .env 파일 로드 (OPENAI_API_KEY 사용)
load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")

# 테스트할 Python 코드 (간단한 예시)
sample_code = '''
def greet(name):
    print(f"Hello, {name}!")
'''

# 변환기 실행
if __name__ == "__main__":
    print("🔧 단일 코드 변환 실행 중...\n")
    run_pipeline_with_rag(sample_code, api_key)