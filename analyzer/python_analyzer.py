
import ast

class PythonAnalyzer:
    def __init__(self, file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            self.code = f.read()
        self.tree = ast.parse(self.code)
        self._add_parents(self.tree)

    def _add_parents(self, node):
        for child in ast.iter_child_nodes(node):
            child.parent = node
            self._add_parents(child)

    def _extract_calls(self, node):
        calls = []
        for n in ast.walk(node):
            if isinstance(n, ast.Call):
                func_name = self._get_full_name(n.func)
                if func_name:
                    calls.append(func_name)
        return calls

    def _get_full_name(self, node):
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            value = self._get_full_name(node.value)
            return f"{value}.{node.attr}" if value else node.attr
        return None

    def _summarize_body(self, node):
        for stmt in node.body:
            if isinstance(stmt, (ast.Return, ast.Expr, ast.Assign)):
                return ast.unparse(stmt).strip()
        return "..."

    def extract_functions(self):
        results = []
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                class_name = None
                parent = getattr(node, 'parent', None)
                while parent:
                    if isinstance(parent, ast.ClassDef):
                        class_name = parent.name
                        break
                    parent = getattr(parent, 'parent', None)

                start_line = getattr(node, "lineno", -1)
                end_line = getattr(node, "end_lineno", -1)

                results.append({
                    "name": node.name,
                    "class": class_name,
                    "calls": self._extract_calls(node),
                    "body": self._summarize_body(node),
                    "full_body": ast.unparse(node),
                    "decorators": [ast.unparse(d) for d in node.decorator_list],
                    "is_async": isinstance(node, ast.AsyncFunctionDef),
                    "line_range": f"L{start_line}-L{end_line}" if start_line > 0 and end_line > 0 else "unknown"
                })
        return results
