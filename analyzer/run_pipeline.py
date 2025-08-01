import os
import zipfile
import json
import shutil
from .java_analyzer import JavaAnalyzer
from .python_analyzer import PythonAnalyzer
from .structure_mapper import StructureMapper
from .xml_mapper_analyzer import XmlMapperAnalyzer

def run_pipeline(zip_file_path: str):
    extract_dir = "extracted_files"
    base_zip_name = os.path.basename(zip_file_path)

    print(f"--- 0단계: 소스 코드 준비 ---")
    if os.path.exists(extract_dir):
        shutil.rmtree(extract_dir)
    with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
        zip_ref.extractall(extract_dir)
    print(f"'{zip_file_path}' 압축 해제 완료.\n")

    source_files = []
    for root, _, files in os.walk(extract_dir):
        for file in files:
            if file.endswith((".java", ".py", ".xml")):
                source_files.append(os.path.join(root, file))

    print(f"--- 1단계: XML 매퍼 분석 ---")
    query_bank = {}
    xml_files = [f for f in source_files if f.endswith(".xml") and 'src/main/resources' in f]
    for xml_file in xml_files:
        analyzer = XmlMapperAnalyzer(xml_file)
        queries = analyzer.get_queries()
        query_bank.update(queries)
    print(f"→ 총 {len(query_bank)}개 SQL 쿼리를 쿼리 뱅크에 로드했습니다.\n")

    print(f"--- 2단계: 소스 코드 정보 추출 ---")
    all_classes = []
    all_functions = []
    source_code_files = [f for f in source_files if f.endswith((".java", ".py"))]
    for file_path in source_code_files:
        lang = "java" if file_path.endswith(".java") else "python"
        rel_path = os.path.relpath(file_path, extract_dir)
        source_info = {"zip_file": base_zip_name, "rel_path": rel_path, "language": lang}
        analyzer = JavaAnalyzer(file_path, query_bank=query_bank) if lang == "java" else PythonAnalyzer(file_path)

        if not analyzer.is_parsed:
            continue

        # python_analyzer로부터 상속 정보를 받기 위해 classes 정보에 bases 추가
        classes = analyzer.extract_classes()
        for class_info in classes:
            class_info["source_info"] = source_info
            all_classes.append(class_info)

        functions = analyzer.extract_functions()
        for func_info in functions:
            func_info["source_info"] = source_info
            all_functions.append(func_info)

    print(f"→ 총 {len(all_classes)}개 클래스, {len(all_functions)}개 함수 정보 추출 완료.\n")

    print(f"--- 3단계: 아키텍처 역할 추론 ---")
    mapper = StructureMapper()

    class_role_map = {}
    for class_info in all_classes:
        class_functions = [f for f in all_functions if f.get("class") == class_info.get("name") and f.get("source_info", {}).get("rel_path") == class_info.get("source_info", {}).get("rel_path")]
        class_info_with_functions = {**class_info, "functions": class_functions}

        role_info = mapper.infer_class_role(class_info_with_functions)
        class_info['role'] = role_info
        class_role_map[class_info['name']] = role_info['type']
        print(f"클래스 '{class_info['name']}'의 역할 추론 → {role_info['type']}")

    # *** 주요 수정 사항: 독립 함수의 역할 추론 로직 변경 ***
    for func_info in all_functions:
        parent_class_name = func_info.get("class")
        # 함수가 클래스에 속한 경우
        if parent_class_name and parent_class_name in class_role_map:
            parent_role = class_role_map[parent_class_name]
            func_role_type = f"{parent_role}_METHOD"
            if func_info['name'] in ['__init__', parent_class_name]:
                func_role_type = "CONSTRUCTOR"

            func_info['role'] = {
                "type": func_role_type,
                "confidence": 1.0,
                "evidence": [f"Inferred from parent class role: {parent_role}"]
            }
        # 함수가 클래스에 속하지 않은 독립 함수인 경우
        else:
             role_info = mapper.infer_standalone_function_role(func_info)
             func_info['role'] = role_info
             print(f"독립 함수 '{func_info['name']}'의 역할 추론 → {role_info['type']}")

    print("\n--- 4단계: 최종 결과 저장 ---")
    output_functions_file = "functions.jsonl"
    output_classes_file = "classes.jsonl"

    with open(output_classes_file, "w", encoding="utf-8") as f:
        for item in all_classes:
            item.pop('functions', None)
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    with open(output_functions_file, "w", encoding="utf-8") as f:
        for item in all_functions:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"분석 완료.")
    print(f"→ {output_classes_file} 에 {len(all_classes)}개 클래스 정보 저장됨")
    print(f"→ {output_functions_file} 에 {len(all_functions)}개 함수 정보 저장됨")


if __name__ == "__main__":
    sample_zip = "samples/flask-realworld-example-app-master.zip"
    if not os.path.exists(sample_zip):
        print(f"오류: 샘플 파일 '{sample_zip}'을 찾을 수 없습니다.")
    else:
        run_pipeline(sample_zip)