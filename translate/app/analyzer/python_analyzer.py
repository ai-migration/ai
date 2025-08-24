import ast

def _name_from_base(node):
    # models.Model / rest_framework.views.APIView / Generic[T] 등 폭넓게 커버
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parts = []
        cur = node
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))
    if isinstance(node, ast.Subscript):  # Generic[T] 케이스
        return _name_from_base(node.value)
    return None

def _decorator_name(d):
    if isinstance(d, ast.Name):
        return d.id
    if isinstance(d, ast.Attribute):
        parts = []
        cur = d
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))
    if isinstance(d, ast.Call):
        return _decorator_name(d.func)
    return None

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
                if node.name == "Meta":
                    continue
                bases = [(_name_from_base(b) or "") for b in node.bases]
                bases_tail = [b.split(".")[-1] if b else "" for b in bases]
                decos = list(filter(None, [_decorator_name(d) for d in node.decorator_list]))
                classes.append({
                    "name": node.name,
                    "type": "ClassDef",
                    "bases": bases_tail,                  # (스키마 유지) 끝 토큰만 사용
                    "decorators": decos,                  # 클래스 데코레이터는 '@' 없이
                    "body": ast.get_source_segment(self.code, node)
                })
        return classes

    def extract_functions(self):
        if not self.is_parsed: return []
        functions = []

        def _collect(fn, class_name=None):
            decos = list(filter(None, [_decorator_name(d) for d in fn.decorator_list]))
            # 함수 데코레이터는 기존처럼 '@' 프리픽스 유지
            decorators_list = [f"@{d}" for d in decos]
            functions.append({
                "name": fn.name,
                "class": class_name,
                "decorators": decorators_list,
                "calls": self.extract_calls(fn),
                "body": ast.get_source_segment(self.code, fn),
                "line_range": f"L{fn.lineno}-L{fn.end_lineno}"
            })

        for node in self.tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _collect(node)

        for class_node in ast.walk(self.tree):
            if isinstance(class_node, ast.ClassDef):
                if class_node.name == "Meta": continue
                for node in class_node.body:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        _collect(node, class_name=class_node.name)
        return functions

    def extract_calls(self, node=None):
        if node is None:
                node = self.tree
        if not node:
            return []
        calls = []
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                name = ""
                if isinstance(sub.func, ast.Name):
                    name = sub.func.id
                elif isinstance(sub.func, ast.Attribute):
                    parts = []
                    cur = sub.func
                    while isinstance(cur, ast.Attribute):
                        parts.append(cur.attr)
                        cur = cur.value
                    if isinstance(cur, ast.Name):
                        parts.append(cur.id)
                    name = ".".join(reversed(parts))
                if name:
                    calls.append({"target": name, "type": "internal"})
        return calls
