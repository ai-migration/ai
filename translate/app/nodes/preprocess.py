from analyzer.file_extractor import FileExtractor
import os

def preprocessing(state: State) -> State:
    """
    업로드된 ZIP 압축 파일을 해제하고, 지원하는 소스 파일을 탐색합니다.

    이 함수는 ``state['extract_dir']``에 압축 해제 디렉터리를,
    ``state['code_files']``에는 탐색된 모든 소스 파일의 (절대경로, 언어) 튜플 리스트를 저장합니다.

    ``state['input_zip']``에 업로드된 ZIP 파일 경로가 들어 있어야 하며,
    해당 경로가 존재하지 않으면 아무 작업도 수행하지 않습니다.
    """
    zip_path = state.get('input_zip')
    if not zip_path or not os.path.exists(zip_path):
        # Nothing to do if no archive is provided
        return state

    extractor = FileExtractor(zip_path)
    extract_dir = extractor.extract_zip()
    code_files = extractor.find_supported_code_files()
    state['extract_dir'] = extract_dir
    state['code_files'] = code_files
    return state