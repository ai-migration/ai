# app/nodes/analyze.py
import os, re, json, logging
from translate.app.states import State
from analyzer.python_analyzer import PythonAnalyzer
from analyzer.java_analyzer import JavaAnalyzer
from analyzer.xml_mapper_analyzer import XmlMapperAnalyzer
from analyzer.structure_mapper import StructureMapper
from analyzer.external_usage_detector import ExternalUsageDetector

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def analyze_python(state: State) -> State:
    """
    명세서 기반 Python 프로젝트 분석 및 결과 파일 저장
    """
    logging.info("Executing node: analyze_python")
    # 1. 정보 추출 및 역할 추론 (기존 로직과 유사하게 진행)
    all_classes, all_functions = [], []
    mapper = StructureMapper()
    base_zip_name = os.path.basename(state.get('input_path', ''))
    extract_dir = state.get('extract_dir')

    for file_path, lang in state.get('code_files', []):
        if lang != 'python': continue

        rel_path = os.path.relpath(file_path, extract_dir)
        source_info = {"zip_file": base_zip_name, "rel_path": rel_path, "language": lang}

        analyzer = PythonAnalyzer(file_path)
        if not analyzer.is_parsed: continue

        # 외부 호출 탐지기 사용
        ext_detector = ExternalUsageDetector(analyzer.code)
        external_calls_in_file = ext_detector.detect()

        py_funcs = analyzer.extract_functions()
        for func in py_funcs:
            func['source_info'] = source_info
            # 함수별 외부 호출 정보 추가
            func['external_calls'] = [call for call in external_calls_in_file if call in func.get('body', '')]
            all_functions.append(func)

        py_classes = analyzer.extract_classes()
        for cls in py_classes:
            cls['source_info'] = source_info
            all_classes.append(cls)

    # 역할 추론
    for cls in all_classes:
        class_methods = [f for f in all_functions if f.get('class') == cls.get('name')]
        cls['role'] = mapper.infer_class_role({**cls, "functions": class_methods})
    for func in all_functions:
        if not func.get('class'):
            func['role'] = mapper.infer_standalone_function_role(func)

    state['classes'], state['functions'] = all_classes, all_functions
    logging.info(f"Python analysis complete: {len(all_classes)} classes, {len(all_functions)} functions.")

    # 2. 결과 파일 저장 (명세서 5단계)
    output_dir = "output"
    if not os.path.exists(output_dir): os.makedirs(output_dir)

    output_classes_file = os.path.join(output_dir, "classes.jsonl")
    with open(output_classes_file, "w", encoding="utf-8") as f:
        for item in all_classes:
            item.pop('functions', None) # 저장 시에는 'functions' 키 제거
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    output_functions_file = os.path.join(output_dir, "functions.jsonl")
    with open(output_functions_file, "w", encoding="utf-8") as f:
        for item in all_functions:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    logging.info(f"Python analysis results saved to '{output_classes_file}' and '{output_functions_file}'")
    state['report_files'] = [output_classes_file, output_functions_file]

    return state


def analyze_java(state: State) -> State:
    """
    명세서 기반 Java 프로젝트 분석 및 결과 파일 저장
    """
    logging.info("Executing node: analyze_java")
    # 1. 정보 추출 및 역할 추론
    all_classes, all_functions, query_bank = [], [], {}
    mapper = StructureMapper()
    base_zip_name = os.path.basename(state.get('input_path', ''))
    extract_dir = state.get('extract_dir')

    for file_path, lang in state.get('code_files', []):
        if lang == 'xml' and 'src/main/resources' in file_path:
            query_bank.update(XmlMapperAnalyzer(file_path).get_queries())
    for file_path, lang in state.get('code_files', []):
        if lang != 'java': continue
        rel_path = os.path.relpath(file_path, extract_dir)
        source_info = {"zip_file": base_zip_name, "rel_path": rel_path, "language": lang}
        analyzer = JavaAnalyzer(file_path, query_bank=query_bank)
        if not analyzer.is_parsed: continue
        for cls in analyzer.extract_classes():
            cls['source_info'] = source_info
            cls['role'] = mapper.infer_class_role(cls)
            all_classes.append(cls)

    # 2. 결과 파일 저장 (명세서 5단계 - Feature 그룹핑 포함)
    output_dir = "output"
    if not os.path.exists(output_dir): os.makedirs(output_dir)

    classes_by_feature = {}
    for cls in all_classes:
        class_name = cls.get("name", "")
        match = re.search(r'^(.*?)(Controller|Service|ServiceImpl|Repository|DAO|VO|Dto|Entity|Config|Exception|Util|Filter|Jwt|Impl|Tests|Test)$', class_name, re.IGNORECASE)
        feature = "unknown"
        if match and match.group(1):
             feature_candidate = re.sub(r'^(Res|Req)', '', match.group(1), flags=re.IGNORECASE)
             feature = feature_candidate.lower() if feature_candidate else class_name.lower()
        elif not match:
             feature = class_name.lower()
        if class_name.endswith("Application"): feature = "app"
        classes_by_feature.setdefault(feature, []).append(cls)

    java_analysis_output = []
    for feature, classes in classes_by_feature.items():
        feature_set = {}
        for cls in classes:
            role = cls.get('role', {}).get('type', 'unknown').lower()
            if role == 'serviceimpl': role = 'service'
            path = cls.get('source_info',{}).get('rel_path')
            feature_set.setdefault(role, []).append(path)
        if feature_set: java_analysis_output.append({feature: feature_set})

    output_file_name = os.path.join(output_dir, "analysis_results.json")
    with open(output_file_name, "w", encoding="utf-8") as f:
        json.dump(java_analysis_output, f, ensure_ascii=False, indent=4)

    logging.info(f"Java analysis results saved to '{output_file_name}'")
    state['report_files'] = [output_file_name]

    # State에는 상세 정보도 저장
    state['classes'] = all_classes
    state['java_analysis'] = java_analysis_output

    return state