import os
import json
import logging
import tempfile
# import zipfile # 더미 파일을 만들지 않으므로 zipfile은 필요 없습니다.
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END

# ... (파일 상단의 다른 import 구문 및 클래스 정의는 그대로 둡니다) ...
from translate.app.states import State
from translate.app.nodes.preprocess import preprocessing
from translate.app.nodes.detect import detect_language, select_lang
from translate.app.nodes.analyze import analyze_python, analyze_java

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class AnalysisTestAgent:
    # ... (클래스 내용은 그대로 둡니다) ...
    def build_graph(self):
        builder = StateGraph(State)
        builder.add_node('preprocessing', preprocessing)
        builder.add_node('detect', detect_language)
        builder.add_node('analyze_python', analyze_python)
        builder.add_node('analyze_java', analyze_java)
        builder.add_edge(START, 'preprocessing')
        builder.add_edge('preprocessing', 'detect')
        builder.add_conditional_edges(
            'detect', select_lang,
            {'python': 'analyze_python', 'java': 'analyze_java', 'unknown': END}
        )
        builder.add_edge('analyze_python', END)
        builder.add_edge('analyze_java', END)
        return builder.compile()

# --- 메인 실행 블록 (수정된 부분) ---
if __name__ == '__main__':
    agent = AnalysisTestAgent()
    graph = agent.build_graph()

    sample_zip_name = "react-spring-blog-backend-main.zip"
    input_zip_path = os.path.join("samples", sample_zip_name)

    if not os.path.exists(input_zip_path):
        logging.error(f"샘플 파일을 찾을 수 없습니다: {input_zip_path}")
    else:
        # --- 임시 디렉토리 생명주기 관리 수정 ---
        # with 구문을 사용하여 코드 블록 전체에서 임시 디렉토리가 유지되도록 합니다.
        with tempfile.TemporaryDirectory() as temp_dir_path:
            logging.info(f"Created temporary directory: {temp_dir_path}")

            # 초기 상태에 input_path와 함께 extract_dir 경로를 지정해줍니다.
            initial_state = {
                "input_path": input_zip_path,
                "extract_dir": temp_dir_path
            }
            final_state = None

            try:
                logging.info(f"Analyzing sample file: {input_zip_path}")
                final_state = graph.invoke(initial_state)

                print("\n" + "="*50)
                print("AGENT ANALYSIS TEST RUN COMPLETE: FINAL STATE")
                print("="*50)
                print(json.dumps(final_state, indent=2, ensure_ascii=False))

            except Exception as e:
                logging.error(f"An error occurred during the agent execution: {e}", exc_info=True)

        logging.info(f"Temporary directory {temp_dir_path} cleaned up.")