def detect_language(state: State) -> State:
    """
    프로젝트에서 사용된 주요 프로그래밍 언어를 감지합니다.

    전처리 단계에서 수집한 확장자를 기준으로 Python 파일이 있으면 'python'을,
    그렇지 않고 Java 파일이 있으면 'java'를 설정합니다.
    둘 다 없는 경우는 'unknown'으로 처리됩니다.
    """
    code_files = state.get('code_files') or []
    langs = {lang for _, lang in code_files}
    if 'python' in langs:
        state['language'] = 'python'
    elif 'java' in langs:
        state['language'] = 'java'
    else:
        state['language'] = 'unknown'
    return state

def select_lang(state: State) -> str:
    """    조건 분기에서 사용할 언어 값을 반환합니다."""
    return state.get('language', 'unknown')