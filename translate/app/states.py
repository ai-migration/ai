from typing import List, Optional, Tuple, Dict
from typing_extensions import Annotated
from typing import TypedDict
import operator

class State(TypedDict, total=False):
    # 파이프라인 공통 상태
    language: Optional[str]          # 'python' | 'java'
    framework: Optional[str]
    egov_version: Optional[str]
    input_path: str                  # Zip 파일 경로 (preprocessing에서 설정)
    extract_dir: str                 # Zip 해제 경로 (preprocessing에서 설정)

    # 수집 결과
    code_files: Annotated[List[Tuple[str, str]], operator.add]  # [(abs_path, lang)]
    classes:    Annotated[List[dict], operator.add]             # 분석된 클래스들
    functions:  Annotated[List[dict], operator.add]             # 분석된 함수들

    # 요약/부가
    java_analysis: Annotated[List[dict], operator.add]          # Java feature별 매핑
    report_files:  Annotated[List[str],  operator.add]          # 산출물 경로 누적

class ConversionEgovState(TypedDict, total=False):
    user_id: int
    job_id: int
    input_path: dict
    controller: List[dict]
    controller_egov: List[dict]
    controller_report: Dict[str, List[str]]
    service: List[dict]
    service_egov: List[dict]
    service_report: Dict[str, List[str]]
    serviceimpl: List[dict]
    serviceimpl_egov: List[dict]
    serviceimpl_report: Dict[str, List[str]]
    vo: List[dict]
    vo_egov: List[dict]
    vo_report: Dict[str, List[str]]
    retrieved: List[dict]
    validate: str
    next_role: str
    next_step: str
    features: list
    current_feature_idx: int
