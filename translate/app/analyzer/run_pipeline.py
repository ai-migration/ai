import os
import json
import re
from dataclasses import dataclass, asdict

# 실제 프로젝트 구조에 맞게 import 경로를 조정해야 할 수 있습니다.
# 예: from .java_analyzer import JavaAnalyzer
from .java_analyzer import JavaAnalyzer
from .python_analyzer import PythonAnalyzer
from .structure_mapper import StructureMapper
from .xml_mapper_analyzer import XmlMapperAnalyzer
from .file_extractor import FileExtractor


# @dataclass
# class Document:
#     page_content: str
#     metadata: dict

def run_pipeline(zip_file_path: str, output_dir: str = "output"):
    """
    모듈화된 코드 분석 파이프라인 (Python/Java 처리 분기 개선)
    """
    base_zip_name = os.path.basename(zip_file_path)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    print("--- 1단계: 소스 코드 파일 추출 ---")
    file_extractor = FileExtractor(zip_file_path)
    extract_dir = file_extractor.extract_zip()
    all_files = file_extractor.find_supported_code_files()
    print(f"'{zip_file_path}'에서 총 {len(all_files)}개의 지원 파일을 찾았습니다.\n")

    detected_langs = {lang for _, lang in all_files if lang in ['java', 'python']}

    print("--- 2단계: XML 매퍼 분석 (Java 프로젝트에만 해당) ---")
    query_bank = {}
    if 'java' in detected_langs:
        xml_files = [path for path, lang in all_files if lang == 'xml' and 'src/main/resources' in path]
        for xml_file in xml_files:
            analyzer = XmlMapperAnalyzer(xml_file)
            query_bank.update(analyzer.get_queries())
        print(f"→ 총 {len(query_bank)}개의 SQL 쿼리를 쿼리 뱅크에 로드했습니다.\n")

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
        if lang == 'python':
            functions = analyzer.extract_functions()
            for func_info in functions:
                func_info["source_info"] = source_info
                all_functions.append(func_info)
    print(f"→ 총 {len(all_classes)}개 클래스, {len(all_functions)}개 함수 정보 추출 완료.\n")

    print("--- 4단계: 아키텍처 역할 추론 ---")
    mapper = StructureMapper()
    for class_info in all_classes:
        py_class_functions = []
        if class_info.get("source_info", {}).get("language") == 'python':
            py_class_functions = [f for f in all_functions if f.get("class") == class_info.get("name")]
        class_info_with_functions = {**class_info, "functions": py_class_functions}
        role_info = mapper.infer_class_role(class_info_with_functions)
        class_info['role'] = role_info
        print(f"클래스 '{class_info['name']}'의 역할 추론 → {role_info['type']}")
    for func_info in all_functions:
        if not func_info.get("class"):
            role_info = mapper.infer_standalone_function_role(func_info)
            func_info['role'] = role_info
            print(f"독립 함수 '{func_info['name']}'의 역할 추론 → {role_info['type']}")
    print("")

    # --- 5단계: 최종 결과 저장 ---
    print("--- 5단계: 최종 결과 저장 ---")

    if 'python' in detected_langs:
        output_classes_file = os.path.join(output_dir, "classes.jsonl")
        output_functions_file = os.path.join(output_dir, "functions.jsonl")
        python_classes = [c for c in all_classes if c.get("source_info", {}).get("language") == 'python']
        with open(output_classes_file, "w", encoding="utf-8") as f:
            for item in python_classes:
                item.pop('functions', None)
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        with open(output_functions_file, "w", encoding="utf-8") as f:
            for item in all_functions:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(f"분석 완료: Python 프로젝트")
        print(f"→ {output_classes_file} 에 {len(python_classes)}개 클래스 정보 저장됨")
        print(f"→ {output_functions_file} 에 {len(all_functions)}개 함수 정보 저장됨")

    elif 'java' in detected_langs and 'python' not in detected_langs:
        java_classes_with_feature = []

        # 1. 각 클래스에 feature 정보 추가
        for class_info in all_classes:
            if class_info.get("source_info", {}).get("language") != 'java':
                continue

            class_name = class_info.get("name", "")
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

            class_info['feature'] = feature
            java_classes_with_feature.append(class_info)

        # 2. Feature를 기준으로 클래스들을 그룹화
        classes_by_feature = {}
        for class_info in java_classes_with_feature:
            feature = class_info['feature']
            if feature not in classes_by_feature:
                classes_by_feature[feature] = []
            classes_by_feature[feature].append(class_info)

        # 3. 최종 출력 형식으로 변환
        output_list = []
        for feature, classes in classes_by_feature.items():
            feature_set = {}
            for cls in classes:
                role = cls.get('role', {}).get('type', '').lower()
                path = cls.get('source_info', {}).get('rel_path', '')

                # 역할 매핑: service와 service_impl을 'service'로 통일
                if role not in feature_set:
                    feature_set[role] = []
                feature_set[role].append(path)


            if feature_set:
                output_list.append(feature_set)

        # 4. JSON 파일로 저장
        output_file_name = os.path.join(output_dir, "analysis_results.json")
        with open(output_file_name, "w", encoding="utf-8") as f:
            json.dump(output_list, f, ensure_ascii=False, indent=4)

        print(f"분석 완료: 기능(feature)별 파일 묶음을 '{output_file_name}'에 저장했습니다.")


if __name__ == "__main__":
    # 테스트를 위한 샘플 zip 파일 경로
    sample_zip = "samples/flask-realworld-example-app-master.zip"
    if not os.path.exists(sample_zip):
        print(f"오류: 샘플 파일 '{sample_zip}'을 찾을 수 없습니다.")
    else:
        run_pipeline(sample_zip)