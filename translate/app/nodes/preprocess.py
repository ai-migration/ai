# app/nodes/preprocess.py
import os
import logging
import tempfile
from translate.app.states import State
from translate.app.analyzer.file_extractor import FileExtractor

# 로깅 기본 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def preprocessing(state: State) -> State:
    """
    주어진 extract_dir 경로에 ZIP 파일의 압축을 해제하고 소스 파일을 탐색합니다.
    FileExtractor가 dict를 반환하더라도, 다음 단계 호환을 위해 (path, lang) 튜플로 정규화합니다.
    """
    logging.info("Executing node: preprocessing")
    input_path = state.get('input_path')
    extract_dir = state.get('extract_dir')

    if not all([input_path, extract_dir]):
        logging.error("Input path or extract directory not provided in state.")
        state['code_files'] = []
        return state

    try:
        extractor = FileExtractor(input_path, extract_dir)
        extractor.extract_zip()
        raw = extractor.find_supported_code_files()  # dict 또는 tuple 혼용 가능

        norm = []
        for it in (raw or []):
            if isinstance(it, dict):
                p = it.get('path') or it.get('abs_path') or it.get('file')
                l = (it.get('language') or it.get('lang') or '').strip().lower()
            else:
                try:
                    p, l = it
                    l = (l or '').strip().lower()
                except Exception:
                    continue
            if not p:
                continue
            # 가능하면 절대경로로 고정(분석 단계에서 파일 접근 안정)
            norm.append((os.path.abspath(p), l))

        state['code_files'] = norm
        logging.info(f"Extracted to '{extract_dir}' and found {len(state['code_files'])} supported files.")
    except Exception as e:
        logging.error(f"Preprocessing failed: {e}", exc_info=True)
        state['code_files'] = []

    return state