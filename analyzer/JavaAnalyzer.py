import re

class JavaAnalyzer:
    def __init__(self, file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            self.code = f.read()

    def extract_functions(self):
        pattern = re.compile(r"(public|private|protected)\s+\w+\s+(\w+)\s*\([^)]*\)\s*{")
        matches = pattern.findall(self.code)
        results = []
        for match in matches:
            results.append({
                "name": match[1],
                "body": "...",  # Java 전체 method body는 현재 생략 or 추출 확장 가능
                "decorators": []
            })
        return results