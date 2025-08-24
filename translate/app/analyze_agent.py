import os
import json
import logging
import tempfile
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END

from translate.app.states import State
from translate.app.nodes.preprocess import preprocessing
from translate.app.nodes.detect import detect_language, select_lang
from translate.app.nodes.analyze import analyze_python, analyze_java

load_dotenv()

# 콘솔은 요약 위주
logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - %(message)s')

class AnalysisAgent:
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

if __name__ == '__main__':
    agent = AnalysisAgent()
    graph = agent.build_graph()

    sample_zip_name = "models.zip"
    input_zip_path = r'C:\Users\User\Desktop\dev\project\0811test.zip' 

    if not os.path.exists(input_zip_path):
        logging.error(f"샘플 파일을 찾을 수 없습니다: {input_zip_path}")
    else:
        with tempfile.TemporaryDirectory() as temp_dir_path:
            logging.info(f"Created temporary directory: {temp_dir_path}")

            initial_state = {"input_path": input_zip_path, "extract_dir": temp_dir_path}
            try:
                final_state = graph.invoke(initial_state)

                # ===== 콘솔엔 요약만 =====
                summary = {
                    "input_zip": os.path.basename(input_zip_path),
                    "extract_dir": temp_dir_path,
                    "report_files": final_state.get("report_files", []),
                    "counts": {
                        "classes": len(final_state.get("classes", [])) if isinstance(final_state.get("classes"), list) else None,
                        "functions": len(final_state.get("functions", [])) if isinstance(final_state.get("functions"), list) else None,
                    },
                    "language": final_state.get("language"),
                    "framework": final_state.get("framework"),
                }
                print("\n" + "="*50)
                print("AGENT ANALYSIS TEST RUN COMPLETE: SUMMARY")
                print("="*50)
                print(json.dumps(summary, indent=2, ensure_ascii=False))

                # ===== 전체 상태는 파일 저장 =====
                os.makedirs("output", exist_ok=True)
                full_path = os.path.join("output", "final_state.json")
                with open(full_path, "w", encoding="utf-8") as f:
                    json.dump(final_state, f, ensure_ascii=False, indent=2)
                print(f"\n(full state saved to: {full_path})")

            except Exception as e:
                logging.error(f"Agent execution error: {e}", exc_info=True)
