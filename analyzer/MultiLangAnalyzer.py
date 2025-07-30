from analyzer.python_analyzer import PythonAnalyzer
from analyzer.java_analyzer import JavaAnalyzer

class MultiLangAnalyzer:
    def __init__(self, structure_mapper):
        self.structure_mapper = structure_mapper

    def analyze(self, file_path: str, language: str) -> list:
        if language == 'python':
            analyzer = PythonAnalyzer(file_path)
        elif language == 'java':
            analyzer = JavaAnalyzer(file_path)
        else:
            return []  # 분석 불가 언어

        functions = analyzer.extract_functions()

        for func in functions:
            func['role'] = self.structure_mapper.infer_role(func)

        return functions


# 사용 예시
"""
from multi_lang_analyzer import MultiLangAnalyzer
from structure_mapper import StructureMapper

analyzer = MultiLangAnalyzer(structure_mapper=StructureMapper())
results = analyzer.analyze("extracted_files/controller.py", "python")

for func in results:
    print(f"🔍 {func['name']} → 역할: {func['role']}")

"""