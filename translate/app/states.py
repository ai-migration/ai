from typing import TypedDict

class State(TypedDict):
    language: str          # 'python' 또는 'java'
    framework: str
    egov_version: str
    input_path: str        # Zip 파일 경로 (preprocessing에서 설정)
    extract_dir: str       # Zip 해제 경로 (preprocessing에서 설정)
    code_files: list       # [(파일절대경로, 언어)] 리스트
    classes: list          # Python 또는 Java 클래스 정보
    functions: list        # Python 함수 정보
    java_analysis: list    # Java 기능(feature)별 역할 매핑 결과

class CoversionEgovState(TypedDict):
    input_path: dict
    controller: list
    controller_egov: list
    controller_report: dict
    service: list
    service_egov: list
    service_report: dict
    serviceimpl: list
    serviceimpl_egov: list
    serviceimpl_report: dict
    vo: list
    vo_egov: list
    vo_report: dict
    retrieved: list
    validate: str
    next_role: str
    next_step: str