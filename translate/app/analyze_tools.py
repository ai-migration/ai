from crewai import Agent, Task, Crew
from crewai.tools import tool

import xml.etree.ElementTree as ET
import os, re, json, hashlib

from analyzer.file_extractor import FileExtractor
from analyzer.python_analyzer import PythonAnalyzer
from analyzer.java_analyzer import JavaAnalyzer
from analyzer.xml_mapper_analyzer import XmlMapperAnalyzer
from analyzer.structure_mapper import StructureMapper
from analyzer.external_usage_detector import ExternalUsageDetector
from log import Logger
from producer import MessageProducer

logger = Logger(name='consumer').logger
producer = MessageProducer()

def _unwrap_state(s):
    # {"state": {...}} 로 들어오면 벗겨서 {...}만 반환
    if isinstance(s, dict) and "state" in s and isinstance(s["state"], dict):
        return s["state"]
    return s if isinstance(s, dict) else {}

def _rel_to_module(rel_path: str) -> str:
    p = (rel_path or "").replace("\\", "/")
    if p.endswith(".py"): p = p[:-3]
    if p.endswith("__init__"): p = p[:-9]
    return ".".join([seg for seg in p.split("/") if seg])

def _body_hash(obj: dict) -> str:
    body = (obj.get("body") or "")
    return hashlib.md5(body.encode("utf-8")).hexdigest()

IGNORE_SUBSTR = ("tests/", "migrations/", "migrations_test_apps/", "/docs/")
def _skip(path: str) -> bool:
    p = (path or "").replace("\\", "/").lower()
    return any(s in p for s in IGNORE_SUBSTR)
               
@tool("preprocessing")
def preprocessing(input_path: str, extract_dir: str) -> dict:
    """
    주어진 extract_dir 경로에 ZIP 파일의 압축을 해제하고 소스 파일을 탐색합니다.
    """
    logger.info("Executing node: preprocessing")

    if not all([input_path, extract_dir]):
        logger.error(f"Input path or extract directory not provided in state.")
        return {'state': {"input_path": input_path, "extract_dir": extract_dir, "code_files": []}}

    try:
        # FileExtractor가 주어진 경로를 사용하도록 수정합니다.
        extractor = FileExtractor(input_path, extract_dir)
        extractor.extract_zip()
        code_files = extractor.find_supported_code_files()
        logger.info(f"Extracted to '{extract_dir}' and found {len(code_files)} supported files.")
        return {'state': {"input_path": input_path, "extract_dir": extract_dir, "code_files": code_files}}
    except Exception as e:
        logger.error(f"Preprocessing failed: {e}", exc_info=True)
        return {'state': {"input_path": input_path, "extract_dir": extract_dir, "code_files": []}}

@tool("detect_language")
def detect_language(state: dict) -> dict:
    """
    프로젝트의 주요 언어와 프레임워크를 탐지합니다.
    Python 파일이 하나라도 존재하면 최우선으로 Python 프로젝트로 판단합니다.
    """

    code_files = state.get('code_files', [])
    extract_dir = state.get('extract_dir', '')
    # 기본값 설정
    primary_language, framework, egov_version = 'unknown', 'unknown', 'unknown'

    # --- 언어 탐지 로직 수정 시작 ---
    # 프로젝트에 포함된 언어 종류를 확인합니다.
    detected_langs = {f['language'] for f in code_files if f['language'] in ['python', 'java']}

    if 'python' in detected_langs:
        # Python 파일이 있으면 무조건 primary_language를 'python'으로 설정
        primary_language = 'python'
    elif 'java' in detected_langs:
        # Python은 없지만 Java 파일이 있으면 'java'로 설정
        primary_language = 'java'
    else:
        # 둘 다 없으면 'unknown'
        primary_language = 'unknown'
    # --- 언어 탐지 로직 수정 끝 ---

    # 프레임워크 탐지 로직은 결정된 주요 언어에 따라 동일하게 수행됩니다.
    if primary_language == 'java':
        for root, _, files in os.walk(extract_dir):
            if 'pom.xml' in files:
                try:
                    tree = ET.parse(os.path.join(root, 'pom.xml'))
                    root_pom = tree.getroot()
                    ns = {'m': 'http://maven.apache.org/POM/4.0.0'}
                    if root_pom.find('.//m:parent[m:artifactId="spring-boot-starter-parent"]', ns) is not None:
                        framework = 'Spring Boot'
                    egov_dep = root_pom.find('.//m:dependency[m:groupId="egovframework.rte"]', ns)
                    if egov_dep is not None:
                        framework = 'eGovFrame'
                        version_tag = egov_dep.find('m:version', ns)
                        if version_tag is not None: egov_version = version_tag.text
                    if framework != 'unknown': break
                except Exception as e:
                    logger.warning(f"Error parsing pom.xml in {root}: {e}")

    # 상태 업데이트
    state['language'] = primary_language
    state['framework'] = framework
    state['egov_version'] = egov_version
    logger.info(f"Detection result (Python Priority): Language={primary_language}, Framework={framework}, Version={egov_version}")

    return {'state': state}

@tool("analyze_python")
def analyze_python(state: dict) -> dict:
    """
    Python 파일을 분석하고 클래스 및 함수 구조를 추출합니다.
    """
    logger.info("Executing node: analyze_python")
    all_classes, all_functions = [], []
    mapper = StructureMapper()
    base_zip_name = os.path.basename(state.get('input_path', ''))
    extract_dir = state.get('extract_dir')
    '''
    code_files: "code_files": [                                                                                                                                                                                        │
      {                                                                                                                                                                                                    │
        "path": "C:\\Users\\User\\AppData\\Local\\Temp\\tmp3nhyum1v\\BoardController.java",                                                                                                                │
        "language": "java"                                                                                                                                                                                 │
      },                                                                                                                                                                                                   │
      {                                                                                                                                                                                                    │
        "path": "C:\\Users\\User\\AppData\\Local\\Temp\\tmp3nhyum1v\\BoardService.java",                                                                                                                   │
        "language": "java"                                                                                                                                                                                 │
      }                                                                                                                                                                                                    │
    ], 
    '''
    for file in state.get('code_files', []):
        file_path = file['path']
        lang = file['language']
        if lang != 'python' or _skip(file_path):
            continue

        rel_path = os.path.relpath(file_path, extract_dir)
        source_info = {"zip_file": base_zip_name, "rel_path": rel_path, "language": lang}

        analyzer = PythonAnalyzer(file_path)
        if not analyzer.is_parsed:
            continue

        # 외부 호출 탐지기
        ext_detector = ExternalUsageDetector(analyzer.code)
        ext_tokens = ext_detector.detect()
        if isinstance(ext_tokens, (list, tuple, set)):
            ext_tokens = set(map(str, ext_tokens))
        else:
            ext_tokens = None  # 안전 가드

        # 함수
        py_funcs = analyzer.extract_functions()
        for func in py_funcs:
            func['source_info'] = source_info
            # 과탐 방지: extract_calls 타겟과 외부 토큰의 교집합
            if ext_tokens is not None:
                call_targets = {c.get("target") for c in (func.get("calls") or []) if c.get("target")}
                func['external_calls'] = sorted(call_targets & ext_tokens)
            else:
                # fallback: 기존 부분 문자열 방식 (최소 보장)
                body = func.get('body', '')
                func['external_calls'] = [t for t in (ext_detector.detect() or []) if isinstance(t, str) and t in body]
            all_functions.append(func)

        # 클래스
        py_classes = analyzer.extract_classes()
        for cls in py_classes:
            cls['source_info'] = source_info
            all_classes.append(cls)

    # 역할 추론
    for cls in all_classes:
        class_methods = [f for f in all_functions if f.get('class') == cls.get('name') and
                         (f.get('source_info') or {}).get('rel_path') == (cls.get('source_info') or {}).get('rel_path')]
        cls['role'] = mapper.infer_class_role({**cls, "functions": class_methods})
    for func in all_functions:
        if not func.get('class'):
            func['role'] = mapper.infer_standalone_function_role(func)

    # (module, class) 인덱스 (내부용)
    class_index = {}
    for c in all_classes:
        rel = (c.get("source_info") or {}).get("rel_path")
        mod = _rel_to_module(rel or "")
        key_rel = (rel, c.get("name")); key_mod = (mod, c.get("name"))
        class_index[key_rel] = c; class_index[key_mod] = c

    # 중복 제거 (스키마 불변)
    seen_c, uniq_classes = set(), []
    for c in all_classes:
        rel = (c.get("source_info") or {}).get("rel_path")
        key = (rel, c.get("name"), _body_hash(c))
        if key in seen_c: continue
        seen_c.add(key); uniq_classes.append(c)
    all_classes = uniq_classes

    seen_f, uniq_functions = set(), []
    for f in all_functions:
        rel = (f.get("source_info") or {}).get("rel_path")
        key = (rel, f.get("class"), f.get("name"), f.get("line_range"))
        if key in seen_f: continue
        seen_f.add(key); uniq_functions.append(f)
    all_functions = uniq_functions

    # 안정 정렬 (내용 동일, 순서만 고정)
    all_classes.sort(key=lambda c: ((c.get("source_info") or {}).get("rel_path") or "", c.get("name") or ""))
    all_functions.sort(key=lambda f: ((f.get("source_info") or {}).get("rel_path") or "", f.get("class") or "", f.get("name") or "", f.get("line_range") or ""))

    state['classes'], state['functions'] = all_classes, all_functions
    logger.info(f"[PY] 분석 완료 → Classes: {len(all_classes)}, Functions: {len(all_functions)}")

    # 저장 (스키마/파일명 그대로)
    output_dir = "./output"
    os.makedirs(output_dir, exist_ok=True)

    output_classes_file = os.path.join(output_dir, "classes.jsonl")
    with open(output_classes_file, "w", encoding="utf-8") as f:
        for item in all_classes:
            item.pop('functions', None)
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    output_functions_file = os.path.join(output_dir, "functions.jsonl")
    with open(output_functions_file, "w", encoding="utf-8") as f:
        for item in all_functions:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    state['report_files'] = [output_classes_file, output_functions_file]
    return {'state': state}



@tool("analyze_java",)
def analyze_java(state: dict) -> dict:
    """
    Java 파일을 분석하고 클래스 및 메소드 구조를 추출합니다.
    """
    logger.info("Executing node: analyze_java")
    all_classes, query_bank = [], {}
    mapper = StructureMapper()
    base_zip_name = os.path.basename(state.get('input_path', ''))
    extract_dir = state.get('extract_dir')

    # XML Mapper (MyBatis 등)
    for file_path, lang in state.get('code_files', []):
        if lang == 'xml' and 'src/main/resources' in file_path:
            query_bank.update(XmlMapperAnalyzer(file_path).get_queries())

    # 자바 클래스
    for file in state.get('code_files', []):
        file_path = file['path']
        lang = file['language']

        if lang != 'java':
            continue

        rel_path = os.path.relpath(file_path, extract_dir)
        source_info = {"zip_file": base_zip_name, "rel_path": rel_path, "language": lang}

        analyzer = JavaAnalyzer(file_path, query_bank=query_bank)
        if not analyzer.is_parsed:
            continue

        for cls in analyzer.extract_classes():
            cls['source_info'] = source_info
            cls['role'] = mapper.infer_class_role(cls)
            all_classes.append(cls)

    # feature 그룹핑 → 요약
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
            if role == 'serviceimpl': role = 'service'  # 요약은 SERVICE로 통합
            path = cls.get('source_info', {}).get('rel_path')
            feature_set.setdefault(role, []).append(path)
        if feature_set:
            java_analysis_output.append({feature: feature_set})

    output_dir = "./output"
    os.makedirs(output_dir, exist_ok=True)
    output_file_name = os.path.join(output_dir, "analysis_results.json")
    with open(output_file_name, "w", encoding="utf-8") as f:
        json.dump(java_analysis_output, f, ensure_ascii=False, indent=4)

    logger.info(f"[JAVA] 분석 완료 → Classes: {len(all_classes)}")
    state['report_files'] = [output_file_name]
    state['classes'] = all_classes
    state['java_analysis'] = java_analysis_output
    return {'state': state}

@tool("produce_to_kafka")
def produce_to_kafka(state: dict):
    """
    최종 분석 결과를 Kafka로 발행합니다."""
    producer.send_message('agent-res', message=state)
