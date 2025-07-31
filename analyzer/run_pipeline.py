import os
import json
from analyzer.file_extractor import FileExtractor
from analyzer.multi_lang_analyzer import MultiLangAnalyzer
from analyzer.structure_mapper import StructureMapper
from analyzer.class_analyzer import ClassAnalyzer

def run_pipeline(zip_path: str):
    zip_file = os.path.basename(zip_path)
    extractor = FileExtractor(zip_path)
    extract_dir = extractor.extract_zip()
    code_files = extractor.find_supported_code_files()

    structure_mapper = StructureMapper()

    functions_output = []
    classes_output = []
    class_info_map = {} # 클래스 정보를 경로 기준으로 저장할 딕셔너리

    print("--- 1단계: 클래스 구조 분석 ---")
    for path, lang in code_files:
        if lang == "java":
            rel_path = os.path.relpath(path, extract_dir).replace("\\", "/")
            try:
                class_analyzer = ClassAnalyzer(path)
                class_info = class_analyzer.analyze()
                if class_info:
                    class_info["language"] = lang
                    class_info["zip_file"] = zip_file
                    class_info["rel_path"] = rel_path
                    classes_output.append(class_info)
                    class_info_map[rel_path] = class_info # 맵에 저장
            except Exception as e:
                print(f"클래스 분석 오류 {path}: {e}")

    print("\n--- 2단계: 함수 분석 및 역할 추론 ---")
    for path, lang in code_files:
        rel_path = os.path.relpath(path, extract_dir).replace("\\", "/")
        extracted_path = path.replace("\\", "/")

        # 이 파일에 해당하는 클래스 정보를 맵에서 가져옴
        class_info = class_info_map.get(rel_path)

        # 언어에 맞는 분석기 선택
        analyzer = None
        if lang == 'python':
            from analyzer.python_analyzer import PythonAnalyzer
            analyzer = PythonAnalyzer(path)
        elif lang == 'java':
            from analyzer.java_analyzer import JavaAnalyzer
            analyzer = JavaAnalyzer(path)

        if not analyzer:
            continue

        functions = analyzer.extract_functions()

        print(f"분석 파일: {path} / {lang}")
        print(f"→ 클래스: {class_info['name'] if class_info else 'N/A'} / 추출 함수 수: {len(functions)}")

        for func in functions:
            # 클래스 정보를 함께 전달하여 역할 추론
            func['role'] = structure_mapper.infer_role(func, class_info)
            func["language"] = lang
            func["zip_file"] = zip_file
            func["extracted_path"] = extracted_path
            func["rel_path"] = rel_path

            # 필요한 필드만 선택하여 저장
            fields = [
                "name", "class", "role", "calls", "annotations", "body", "full_body",
                "is_async", "zip_file", "extracted_path", "rel_path",
                "line_range", "language"
            ]
            filtered_func = {k: func[k] for k in fields if k in func}
            functions_output.append(filtered_func)

    # --- 결과 저장 ---
    with open("functions.jsonl", "w", encoding="utf-8") as f:
        for item in functions_output:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    with open("classes.jsonl", "w", encoding="utf-8") as f:
        for item in classes_output:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print("\n분석 완료!")
    print(f"→ functions.jsonl 에 {len(functions_output)}개 함수 저장됨")
    print(f"→ classes.jsonl 에 {len(classes_output)}개 클래스 저장됨")

if __name__ == "__main__":
    # 사용 예시: 분석할 zip 파일 경로를 여기에 입력하세요.
    run_pipeline("samples/SpringBoot_Basic-main.zip")