# java_analyzer.py
import javalang
import re
import logging

logger = logging.getLogger(__name__)

class JavaAnalyzer:
    """
    Java 소스 파일을 분석하여 클래스, 함수, 어노테이션, '메서드 호출' 등의 구조를 추출합니다.
    XML 매퍼에서 추출된 쿼리 뱅크를 활용하여 SQL을 매핑합니다.
    """
    def __init__(self, file_path: str, query_bank: dict = None):
        self.file_path = file_path
        self.query_bank = query_bank or {}
        self.tree = None
        self.is_parsed = False

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                self.code = f.read()
                self.lines = self.code.splitlines()
            self.tree = javalang.parse.parse(self.code)
            self.is_parsed = True
        except Exception as e:
            logger.warning(f"[Java Parse Warning] {self.file_path} :: {e}")
            self.lines = []

    def _extract_javadoc_description(self, node):
        if not getattr(node, "position", None):
            return ""
        # node.position 이전의 블록에서 마지막 /** ... */를 찾는다
        doc_comment_block = "\n".join(self.lines[:node.position.line - 1])
        javadoc_match = re.search(r'/\*\*(.*?)\*/', doc_comment_block, re.DOTALL | re.MULTILINE)
        if not javadoc_match:
            return ""
        javadoc_content = javadoc_match.group(1)
        p_tag_match = re.search(r'<p>(.*?)</p>', javadoc_content, re.DOTALL | re.IGNORECASE)
        if p_tag_match:
            description = ' '.join([line.strip().lstrip('*').strip() for line in p_tag_match.group(1).strip().split('\n')])
            return description
        lines = [line.strip().lstrip('*').strip() for line in javadoc_content.split('\n')]
        first_meaningful_line = next((line for line in lines if line and not line.startswith('@')), None)
        return first_meaningful_line or ""

    def extract_classes(self):
        if not self.is_parsed: return []
        classes = []
        for _, node in self.tree.filter(javalang.tree.TypeDeclaration):
            if isinstance(node, (javalang.tree.ClassDeclaration, javalang.tree.InterfaceDeclaration)):
                description = self._extract_javadoc_description(node)
                classes.append({
                    "name": node.name,
                    "type": type(node).__name__,
                    "description": description,
                    "annotations": [ann.name for ann in getattr(node, "annotations", [])],
                    "body": self.code,
                })
        return classes

    def extract_functions(self):
        if not self.is_parsed: return []
        functions = []
        for _, class_node in self.tree.filter(javalang.tree.TypeDeclaration):
            if not isinstance(class_node, (javalang.tree.ClassDeclaration, javalang.tree.InterfaceDeclaration)):
                continue
            nodes_to_process = list(getattr(class_node, "methods", [])) + list(getattr(class_node, "constructors", []))
            for node in nodes_to_process:
                start_pos = getattr(node, "position", None)
                end_pos = self._find_last_position(node)

                # SQL 매핑 (XML or @Query)
                sql_query = None
                dao_name_convention = class_node.name[0].lower() + class_node.name[1:]
                query_id_convention = f"{dao_name_convention}.{node.name}"
                if query_id_convention in self.query_bank:
                    sql_query = self.query_bank[query_id_convention]
                if not sql_query:
                    for ann in getattr(node, "annotations", []):
                        if ann.name == "Query":
                            if hasattr(ann, "element") and hasattr(ann.element, "value"):
                                sql_query = getattr(ann.element, "value", "").strip('"').strip()
                            elif isinstance(getattr(ann, "element", None), list):
                                for pair in ann.element:
                                    if getattr(pair, "name", "") == "value" and hasattr(pair.value, "value"):
                                        sql_query = pair.value.value.strip('"').strip()
                                        break

                functions.append({
                    "name": class_node.name if isinstance(node, javalang.tree.ConstructorDeclaration) else node.name,
                    "class": class_node.name,
                    "calls": self.extract_calls(node),
                    "sql_query": sql_query,
                    "body": self._get_node_text_from_position(getattr(node.body, "position", None),
                                                              self._find_last_position(getattr(node, "body", None)))
                              if getattr(node, "body", None) and isinstance(node.body, javalang.tree.Node) else "",
                    "full_body": self._get_node_text_from_position(start_pos, end_pos),
                    "annotations": [ann.name for ann in getattr(node, "annotations", [])],
                    "line_range": f"L{start_pos.line}-L{end_pos.line}" if start_pos and end_pos else "L?-L?"
                })
        return functions

    def extract_calls(self, method_node):
        """
        메서드 전체 서브트리를 순회하여 호출을 수집.
        target 형식 예: "System.out.println", "restTemplate.getForObject"
        """
        calls = []
        try:
            for _, call in method_node.filter(javalang.tree.MethodInvocation):
                # qualifier는 문자열(예: "System.out" / "this" / "service")일 수 있음
                qualifier = getattr(call, "qualifier", None)
                member = getattr(call, "member", None)
                if not member:
                    continue
                target = f"{qualifier}.{member}" if qualifier else member
                call_type = "internal"
                # 매우 보수적인 외부 SDK 힌트 (패키지명까지는 알기 어려우므로 한정)
                if qualifier and any(q in qualifier for q in ["System.", "java.", "javax.", "jakarta.", "org.springframework.", "com.fasterxml."]):
                    call_type = "external_sdk"
                calls.append({"target": target, "type": call_type})
        except Exception as e:
            logger.debug(f"[extract_calls] skip due to: {e}")
        return calls

    def _get_node_text_from_position(self, start_pos, end_pos):
        if not start_pos or not end_pos or not getattr(self, "lines", None): return ""
        start_line, start_col = start_pos.line - 1, start_pos.column - 1
        end_line, end_col = end_pos.line - 1, end_pos.column
        if start_line >= len(self.lines) or end_line >= len(self.lines): return ""
        if start_line == end_line: return self.lines[start_line][start_col:end_col]
        lines = [self.lines[start_line][start_col:]]
        lines.extend(self.lines[start_line + 1:end_line])
        lines.append(self.lines[end_line][:end_col])
        return "\n".join(lines)

    def _find_last_position(self, node):
        if not getattr(node, "position", None):
            return None
        last = node.position
        if hasattr(node, "children"):
            for child in node.children:
                items = []
                if isinstance(child, javalang.tree.Node):
                    items.append(child)
                elif isinstance(child, list):
                    items.extend([x for x in child if isinstance(x, javalang.tree.Node)])
                for item in items:
                    pos = self._find_last_position(item)
                    if pos and (pos.line > last.line or (pos.line == last.line and pos.column > last.column)):
                        last = pos
        return last
