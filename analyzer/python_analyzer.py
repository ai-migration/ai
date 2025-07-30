import ast

class PythonAnalyzer:
    def __init__(self, file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            self.code = f.read()
        self.tree = ast.parse(self.code)

    def extract_functions(self):
        results = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef):
                results.append({
                    "name": node.name,
                    "body": ast.unparse(node),
                    "decorators": [ast.unparse(d) for d in node.decorator_list]
                })
        return results
