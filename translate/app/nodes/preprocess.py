# app/nodes/preprocess.py
import os
import logging
import tempfile
from app.states import State
from analyzer.file_extractor import FileExtractor

# 로깅 기본 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def preprocessing(state: State) -> State:
    """
    ZIP 파일을 안전한 임시 디렉터리에 해제하고, 지원하는 소스 파일 목록을 생성합니다.
    """
    logging.info("Executing node: preprocessing")
    input_path = state.get('input_path')
    if not input_path or not os.path.exists(input_path):
        logging.error(f"Input path not found: {input_path}")
        state['code_files'] = []
        return state

    try:
        # 임시 디렉터리 생성 및 state에 경로와 객체 저장
        temp_dir = tempfile.TemporaryDirectory()
        state['_temp_dir_obj'] = temp_dir
        state['extract_dir'] = temp_dir.name

        # 제공된 FileExtractor를 사용하여 압축 해제 및 파일 목록 생성
        extractor = FileExtractor(input_path, state['extract_dir'])
        extractor.extract_zip()
        state['code_files'] = extractor.find_supported_code_files()
        logging.info(f"Extracted to '{state['extract_dir']}' and found {len(state.get('code_files',[]))} supported files.")
    except Exception as e:
        logging.error(f"Preprocessing failed: {e}", exc_info=True)
        state['code_files'] = []
    return state