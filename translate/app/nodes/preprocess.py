# app/nodes/preprocess.py
import os
import logging
import tempfile
from translate.app.states import State
from analyzer.file_extractor import FileExtractor

# 로깅 기본 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def preprocessing(state: State) -> State:
    """
    주어진 extract_dir 경로에 ZIP 파일의 압축을 해제하고 소스 파일을 탐색합니다.
    """
    logging.info("Executing node: preprocessing")
    input_path = state.get('input_path')
    # 외부에서 지정한 임시 디렉토리 경로를 받습니다.
    extract_dir = state.get('extract_dir')

    if not all([input_path, extract_dir]):
        logging.error(f"Input path or extract directory not provided in state.")
        state['code_files'] = []
        return state

    try:
        # FileExtractor가 주어진 경로를 사용하도록 수정합니다.
        extractor = FileExtractor(input_path, extract_dir)
        extractor.extract_zip()
        state['code_files'] = extractor.find_supported_code_files()
        logging.info(f"Extracted to '{extract_dir}' and found {len(state.get('code_files',[]))} supported files.")
    except Exception as e:
        logging.error(f"Preprocessing failed: {e}", exc_info=True)
        state['code_files'] = []

    # 임시 디렉토리 객체를 여기서 만들지 않으므로 state에 저장할 필요가 없습니다.
    return state