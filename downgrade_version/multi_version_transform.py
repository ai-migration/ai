import os
from typing import List, Dict
from langchain_community.chat_models import ChatOpenAI
from langchain.prompts import PromptTemplate
from dotenv import load_dotenv
load_dotenv()  # ✅ .env 환경변수 로드

#버전 변환 기능 코드

# 프롬프트 템플릿 로딩 함수
def load_prompt_template(version: str) -> str:
    import os
    prompt_path = os.path.join("docs", "prompt_version_downgrade.txt")
    with open(prompt_path, "r", encoding="utf-8") as f:
        template = f.read()
    return template.replace("{{target_version}}", version)


# 변환 실행 함수
def transform_code_to_versions(input_code: str, versions: List[str], model_name: str = "gpt-4") -> dict:
    llm = ChatOpenAI(
        model=model_name,
        openai_api_key=os.getenv("OPENAI_API_KEY")  # ✅ 여기를 반드시 확인
    )
    results = {}
    for version in versions:
        prompt = load_prompt_template(version).replace("{{input_code}}", input_code)
        output = llm.predict(prompt)
        results[version] = output
    return results

# 실제 실행 로직
if __name__ == "__main__":
    file_path = "examples/TestController.java"

    # 파일 내용 읽기
    with open(file_path, "r", encoding="utf-8") as f:
        input_code = f.read()

    # 변환 대상 버전 리스트 지정
    target_versions = ["2.7.1", "3.2.0", "3.5.1", "3.6.0", "3.7.0", "3.9.0"]

    # 변환 실행
    transformed = transform_code_to_versions(input_code, target_versions)

    # 결과 출력 및 파일 저장
    for version, code in transformed.items():
        print(f"\n📦 [eGovFrame {version}] 변환 결과:")
        print("=" * 60)
        print(code)

        output_path = f"converted/converted_{version}.java"
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(code)







