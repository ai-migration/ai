import ast

class PythonAnalyzer:
    def __init__(self, file_path):
        self.file_path = file_path
        self.tree = None
        self.is_parsed = False

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                self.code = f.read()
            self.tree = ast.parse(self.code)
            self.is_parsed = True
        except Exception as e:
            print(f"⚠️ [Python Parse Warning] Failed to parse file: {self.file_path}\n    Reason: {e}")

    def extract_classes(self):
        if not self.is_parsed: return []
        classes = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef):
                classes.append({
                    "name": node.name,
                    "type": "ClassDef",
                    "bases": [b.id for b in node.bases if isinstance(b, ast.Name)],
                    "decorators": [decorator.id for decorator in node.decorator_list if isinstance(decorator, ast.Name)],
                    "body": ast.get_source_segment(self.code, node)
                })
        return classes

    def extract_functions(self):
        if not self.is_parsed: return []
        functions = []

        for node in self.tree.body:
            if isinstance(node, ast.FunctionDef):
                functions.append(self._extract_function_info(node))

        for class_node in ast.walk(self.tree):
            if isinstance(class_node, ast.ClassDef):
                for node in class_node.body:
                    if isinstance(node, ast.FunctionDef):
                        functions.append(self._extract_function_info(node, class_name=class_node.name))
        return functions

    def _extract_function_info(self, node, class_name=None):
        # *** 주요 수정 사항: 데코레이터 추출 로직 강화 ***
        decorators_list = []
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Name):
                decorators_list.append(f"@{decorator.id}")
            # @blueprint.route 같은 형태 (ast.Attribute) 처리
            elif isinstance(decorator, ast.Attribute) and hasattr(decorator, 'value') and hasattr(decorator.value, 'id'):
                decorators_list.append(f"@{decorator.value.id}.{decorator.attr}")
            # @jwt_required() 같은 호출 형태 (ast.Call) 처리
            elif isinstance(decorator, ast.Call) and hasattr(decorator, 'func') and hasattr(decorator.func, 'id'):
                 decorators_list.append(f"@{decorator.func.id}")

        return {
            "name": node.name,
            "class": class_name,
            "decorators": decorators_list,
            "calls": self.extract_calls(node),
            "body": ast.get_source_segment(self.code, node),
            "line_range": f"L{node.lineno}-L{node.end_lineno}"
        }

    def extract_calls(self, node):
        calls = []
        for sub_node in ast.walk(node):
            if isinstance(sub_node, ast.Call):
                call_name = ""
                if isinstance(sub_node.func, ast.Name):
                    call_name = sub_node.func.id
                elif isinstance(sub_node.func, ast.Attribute):
                    attr = sub_node.func
                    path = []
                    while isinstance(attr, ast.Attribute):
                        path.append(attr.attr)
                        attr = attr.value
                    if isinstance(attr, ast.Name):
                        path.append(attr.id)
                    call_name = ".".join(reversed(path))

                if call_name:
                    calls.append({"target": call_name, "type": "internal"})
        return calls