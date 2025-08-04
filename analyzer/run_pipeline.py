import os
import json
import shutil
import zipfile
import re


from dataclasses import dataclass, asdict

from .java_analyzer import JavaAnalyzer
from .python_analyzer import PythonAnalyzer
from .structure_mapper import StructureMapper
from .xml_mapper_analyzer import XmlMapperAnalyzer
from .file_extractor import FileExtractor

@dataclass
class Document:
    page_content: str
    metadata: dict

def run_pipeline(zip_file_path: str, output_dir: str = "output"):
    """
    모듈화된 코드 분석 파이프라인 (Python/Java 처리 분기 개선)
    """
    base_zip_name = os.path.basename(zip_file_path)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # --- 1단계: 파일 추출 ---
    print("--- 1단계: 소스 코드 파일 추출 ---")
    file_extractor = FileExtractor(zip_file_path)
    extract_dir = file_extractor.extract_zip()
    all_files = file_extractor.find_supported_code_files()
    print(f"'{zip_file_path}'에서 총 {len(all_files)}개의 지원 파일을 찾았습니다.\n")

    detected_langs = {lang for _, lang in all_files if lang in ['java', 'python']}

    # --- 2단계: XML 매퍼 분석 (Java 프로젝트에만 해당) ---
    query_bank = {}
    if 'java' in detected_langs:
        print("--- 2단계: XML 매퍼 분석 ---")
        xml_files = [path for path, lang in all_files if lang == 'xml' and 'src/main/resources' in path]
        for xml_file in xml_files:
            analyzer = XmlMapperAnalyzer(xml_file)
            query_bank.update(analyzer.get_queries())
        print(f"→ 총 {len(query_bank)}개의 SQL 쿼리를 쿼리 뱅크에 로드했습니다.\n")

    # --- 3단계: 소스 코드 정보 추출 ---
    print("--- 3단계: 소스 코드 정보 추출 ---")
    all_classes = []
    all_functions = []
    source_code_files = [(path, lang) for path, lang in all_files if lang in ['java', 'python']]

    for file_path, lang in source_code_files:
        rel_path = os.path.relpath(file_path, extract_dir)
        source_info = {"zip_file": base_zip_name, "rel_path": rel_path, "language": lang}

        analyzer = None
        if lang == 'java':
            analyzer = JavaAnalyzer(file_path, query_bank=query_bank)
        elif lang == 'python':
            analyzer = PythonAnalyzer(file_path)

        if not analyzer or not analyzer.is_parsed: continue

        classes = analyzer.extract_classes()
        for class_info in classes:
            class_info["source_info"] = source_info
            all_classes.append(class_info)

        # Python 파일의 경우에만 함수 정보 추출
        if lang == 'python':
            functions = analyzer.extract_functions()
            for func_info in functions:
                func_info["source_info"] = source_info
                all_functions.append(func_info)

    print(f"→ 총 {len(all_classes)}개 클래스, {len(all_functions)}개 함수 정보 추출 완료.\n")

    # --- 4단계: 아키텍처 역할 추론 ---
    print("--- 4단계: 아키텍처 역할 추론 ---")
    mapper = StructureMapper()
    for class_info in all_classes:
        # Python 클래스의 경우, 해당 클래스에 속한 함수 정보를 함께 전달
        py_class_functions = []
        if class_info.get("source_info", {}).get("language") == 'python':
            py_class_functions = [f for f in all_functions if f.get("class") == class_info.get("name")]

        class_info_with_functions = {**class_info, "functions": py_class_functions}
        role_info = mapper.infer_class_role(class_info_with_functions)
        class_info['role'] = role_info
        print(f"클래스 '{class_info['name']}'의 역할 추론 → {role_info['type']}")

    # Python 독립 함수의 역할 추론
    for func_info in all_functions:
        if not func_info.get("class"): # 클래스에 속하지 않은 함수
            role_info = mapper.infer_standalone_function_role(func_info)
            func_info['role'] = role_info
            print(f"독립 함수 '{func_info['name']}'의 역할 추론 → {role_info['type']}")
    print("")

    # --- 5단계: 최종 결과 저장 ---
    print("--- 5단계: 최종 결과 저장 ---")

    # Python 코드가 있을 경우 classes.jsonl, functions.jsonl 생성
    if 'python' in detected_langs:
        output_classes_file = os.path.join(output_dir, "classes.jsonl")
        output_functions_file = os.path.join(output_dir, "functions.jsonl")

        # Python 클래스 정보만 필터링하여 저장
        python_classes = [c for c in all_classes if c.get("source_info", {}).get("language") == 'python']
        with open(output_classes_file, "w", encoding="utf-8") as f:
            for item in python_classes:
                item.pop('functions', None) # 역할 추론에 사용된 함수 정보는 최종 파일에서 제외
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

        # Python 함수 정보 저장
        with open(output_functions_file, "w", encoding="utf-8") as f:
            for item in all_functions:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

        print(f"분석 완료: Python 프로젝트")
        print(f"→ {output_classes_file} 에 {len(python_classes)}개 클래스 정보 저장됨")
        print(f"→ {output_functions_file} 에 {len(all_functions)}개 함수 정보 저장됨")

    # Java 코드만 있을 경우 기존 로직 수행
    elif 'java' in detected_langs and 'python' not in detected_langs:
        grouped_documents = {}
        java_classes = [c for c in all_classes if c.get("source_info", {}).get("language") == 'java']

        for class_info in java_classes:
            rel_path = class_info['source_info']['rel_path']
            class_name = class_info.get("name", "")

            domain = "unknown"
            norm_path = rel_path.replace('\\', '/')
            base_dir = ""
            if "src/main/java/" in norm_path: base_dir = "src/main/java/"
            elif "src/test/java/" in norm_path: base_dir = "src/test/java/"

            if base_dir:
                package_path = norm_path.split(base_dir)[1]
                package_as_path = os.path.dirname(package_path)
                domain = package_as_path.replace('/', '.')

            feature = "unknown"
            match = re.search(r'^(.*?)(Controller|Service|ServiceImpl|Repository|DAO|VO|Dto|Entity|Config|Exception|Util|Filter|Jwt|Impl|Tests|Test)$', class_name, re.IGNORECASE)
            if match:
                feature_candidate = match.group(1)
                feature_candidate = re.sub(r'^(Res|Req)', '', feature_candidate, flags=re.IGNORECASE)
                feature = feature_candidate.lower() if feature_candidate else class_name.lower()
            else:
                feature = class_name.lower()

            if class_name.endswith("Application"):
                feature = "app"

            doc = Document(
                page_content=f"[description] {class_info.get('description', '')}\n[code]{class_info.get('body', '')}",
                metadata={
                    "title": class_name,
                    "path": rel_path,
                    "type": class_info.get('role', {}).get('type', 'component').upper(),
                    "domain": domain,
                    "feature": feature
                }
            )

            role_key = doc.metadata['type'].lower()
            if role_key not in grouped_documents:
                grouped_documents[role_key] = []

            grouped_documents[role_key].append(asdict(doc))

        output_file_name = os.path.join(output_dir, "analysis_results.json")
        with open(output_file_name, "w", encoding="utf-8") as f:
            json.dump(grouped_documents, f, ensure_ascii=False, indent=4)

        print(f"분석 완료: 그룹화된 결과를 '{output_file_name}'에 저장했습니다.")



if __name__ == "__main__":
    # 테스트를 위한 샘플 zip 파일 경로
    sample_zip = "samples/flask-realworld-example-app-master.zip"
    if not os.path.exists(sample_zip):
        print(f"오류: 샘플 파일 '{sample_zip}'을 찾을 수 없습니다.")
    else:
        run_pipeline(sample_zip)