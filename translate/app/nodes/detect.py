# app/nodes/detect.py
import os
import logging
import xml.etree.ElementTree as ET
from translate.app.states import State

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def detect_language(state: State) -> State:
    """
    프로젝트의 주요 언어와 프레임워크를 탐지합니다.
    Python 파일이 하나라도 존재하면 최우선으로 Python 프로젝트로 판단합니다.
    """
    logging.info("Executing node: detect_language (with Python priority logic)")
    code_files = state.get('code_files', [])
    extract_dir = state.get('extract_dir', '')

    # 기본값 설정
    primary_language, framework, egov_version = 'unknown', 'unknown', 'unknown'

    # --- 언어 탐지 로직 수정 시작 ---
    # 프로젝트에 포함된 언어 종류를 확인합니다.
    detected_langs = {lang for _, lang in code_files if lang in ['python', 'java']}

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
                    logging.warning(f"Error parsing pom.xml in {root}: {e}")

    # 상태 업데이트
    state['language'] = primary_language
    state['framework'] = framework
    state['egov_version'] = egov_version
    logging.info(f"Detection result (Python Priority): Language={primary_language}, Framework={framework}, Version={egov_version}")

    return state

def select_lang(state: State) -> str:
    """조건 분기를 위한 현재 언어를 반환합니다."""
    lang = state.get('language', 'unknown')
    logging.info(f"Routing based on language: {lang}")
    return lang