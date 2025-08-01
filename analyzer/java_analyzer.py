import javalang

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
            print(f"⚠️ [Java Parse Warning] Failed to parse file: {self.file_path}\n    Reason: {e}")

    def extract_classes(self):
        if not self.is_parsed: return []
        classes = []
        for _, node in self.tree.filter(javalang.tree.TypeDeclaration):
            if isinstance(node, (javalang.tree.ClassDeclaration, javalang.tree.InterfaceDeclaration)):
                classes.append({
                    "name": node.name,
                    "type": type(node).__name__,
                    "annotations": [ann.name for ann in node.annotations],
                    "body": self.code,
                })
        return classes

    def extract_functions(self):
        if not self.is_parsed: return []
        functions = []
        for _, class_node in self.tree.filter(javalang.tree.TypeDeclaration):
            if not isinstance(class_node, (javalang.tree.ClassDeclaration, javalang.tree.InterfaceDeclaration)): continue

            nodes_to_process = class_node.methods + class_node.constructors
            for node in nodes_to_process:
                start_pos = node.position
                end_pos = self._find_last_position(node)

                sql_query = None
                dao_name_convention = class_node.name[0].lower() + class_node.name[1:]
                query_id_convention = f"{dao_name_convention}.{node.name}"
                if query_id_convention in self.query_bank:
                    sql_query = self.query_bank[query_id_convention]

                if not sql_query:
                    for ann in node.annotations:
                        if ann.name == 'Query':
                            if isinstance(ann.element, javalang.tree.Literal):
                                sql_query = ann.element.value.strip('"').strip()
                            elif isinstance(ann.element, list):
                                for pair in ann.element:
                                    if pair.name == 'value':
                                        sql_query = pair.value.value.strip('"').strip()
                                        break

                functions.append({
                    "name": class_node.name if isinstance(node, javalang.tree.ConstructorDeclaration) else node.name,
                    "class": class_node.name,
                    "calls": self.extract_calls(node),
                    "sql_query": sql_query,
                    "body": self._get_node_text_from_position(node.body.position, self._find_last_position(node.body)) if node.body and isinstance(node.body, javalang.tree.Node) else "",
                    "full_body": self._get_node_text_from_position(start_pos, end_pos),
                    "annotations": [ann.name for ann in node.annotations],
                    "line_range": f"L{start_pos.line}-L{end_pos.line}" if start_pos and end_pos else "L?-L?"
                })
        return functions

    def extract_calls(self, method_node):
        """
        메서드 노드 내부의 다른 메서드 호출(MethodInvocation)을 추출하는 수정된 메서드.
        """
        calls = []
        # 메서드 body가 없거나 list가 아니면 빈 리스트 반환
        if not hasattr(method_node, 'body') or not isinstance(method_node.body, list):
            return []

        # 메서드 body는 statement의 '리스트'이므로, 각 statement를 순회해야 함
        for statement in method_node.body:
            if not statement:
                continue

            # 각 statement 노드 안에서 MethodInvocation을 필터링
            try:
                for _, call_node in statement.filter(javalang.tree.MethodInvocation):
                    target_parts = []
                    current = call_node

                    # 호출 경로를 재귀적으로 탐색하여 전체 경로 생성
                    while hasattr(current, 'member'):
                        target_parts.append(current.member)
                        if hasattr(current, 'qualifier') and current.qualifier:
                            current = current.qualifier
                        else:
                            break

                    if isinstance(current, str):
                        target_parts.append(current)

                    if not target_parts:
                        continue

                    target = ".".join(reversed(target_parts))

                    call_type = "internal"
                    if any(ext in target.lower() for ext in ["java.", "org.springframework.", "javax.", "jakarta."]):
                        call_type = "external_sdk"
                    calls.append({"target": target, "type": call_type})
            except (AttributeError, TypeError):
                # filter를 지원하지 않는 노드 타입이 있을 수 있으므로 예외 처리
                continue
        return calls

    def _get_node_text_from_position(self, start_pos, end_pos):
        if not start_pos or not end_pos: return ""
        start_line, start_col = start_pos.line - 1, start_pos.column - 1
        end_line, end_col = end_pos.line - 1, end_pos.column
        if start_line >= len(self.lines) or end_line >= len(self.lines): return ""
        if start_line == end_line: return self.lines[start_line][start_col:end_col]
        lines = [self.lines[start_line][start_col:]]
        lines.extend(self.lines[start_line + 1:end_line])
        lines.append(self.lines[end_line][:end_col])
        return "\n".join(lines)

    def _find_last_position(self, node):
        last_pos = node.position if hasattr(node, 'position') and node.position else None
        if hasattr(node, 'children'):
            for child in node.children:
                child_pos = None
                items_to_check = []
                if isinstance(child, javalang.tree.Node): items_to_check.append(child)
                elif isinstance(child, list): items_to_check.extend(item for item in child if isinstance(item, javalang.tree.Node))
                for item in items_to_check:
                    item_pos = self._find_last_position(item)
                    if item_pos and (child_pos is None or item_pos.line > child_pos.line or (item_pos.line == child_pos.line and item_pos.column > child_pos.column)):
                        child_pos = item_pos
                if child_pos and (last_pos is None or (child_pos.line > last_pos.line or (child_pos.line == last_pos.line and child_pos.column > last_pos.column))):
                    last_pos = child_pos
        return last_pos