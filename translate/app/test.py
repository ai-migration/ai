# run_transform_pipeline.py

from analyzer.file_extractor import FileExtractor
from analyzer.multi_lang_analyzer import MultiLangAnalyzer
from analyzer.structure_mapper import StructureMapper
from analyzer.prompt_builder import PromptBuilder
from analyzer.extract_code_block import extract_code_block
from analyzer.egov_frame_writer import EgovFrameWriter
from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")

# 1. 압축 해제 + 코드 파일 수집
extractor = FileExtractor("samples/sample_project.zip")
extractor.extract_zip()
code_files = extractor.find_supported_code_files()

# 2. 분석기 + 구성요소
mapper = StructureMapper()
analyzer = MultiLangAnalyzer(mapper)
prompter = PromptBuilder()
writer = EgovFrameWriter()
client = OpenAI(api_key=api_key)

# 3. 각 파일에 대해 처리
for path, lang in code_files:
    functions = analyzer.analyze(path, lang)

    for func in functions:
        prompt = prompter.build_prompt(func)
        print(f"🚀 Transforming: {func['name']} ({func['role']})")

        # GPT 호출
        res = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )
        output = res.choices[0].message.content
        java_code = extract_code_block(output)

        writer.save_code(
            java_code,
            func_name=func["name"],
            role=func["role"],
            domain="cop",
            feature="bbs"
        )
