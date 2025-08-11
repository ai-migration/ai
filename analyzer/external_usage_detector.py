import ast
import logging

logger = logging.getLogger(__name__)

class ExternalUsageDetector(ast.NodeVisitor):
    """
    소스 코드에서 '외부 호출'로 볼 가능성이 높은 호출을 식별자 토큰으로 추출.
    반환 형식: 정렬된 문자열 리스트 (예: ["requests.get", "openai.ChatCompletion.create", "cursor.execute"])
    """
    # 최상위 모듈 기준 화이트리스트(네임스페이스 루트)
    EXTERNAL_ROOTS = {
        "requests", "httpx", "openai", "urllib", "http", "smtplib",
        "boto3", "botocore", "pymysql", "psycopg2", "sqlite3",
        "mysql", "sqlalchemy", "pymongo", "redis",
    }

    # DB/네트워크 일반 휴리스틱(qualifier에 자주 등장)
    QUALIFIER_HINTS = {"cursor", "connection", "session", "engine", "client", "resource"}

    # 메서드명 휴리스틱
    METHOD_HINTS = {"execute", "fetchone", "fetchall", "query", "get", "post", "put", "delete", "connect"}

    def __init__(self, source_code: str):
        self.external_calls = set()
        try:
            self.tree = ast.parse(source_code)
        except Exception as e:
            logger.warning(f"[ExternalUsageDetector] Parse failed: {e}")
            self.tree = None

    # 유틸: 노드에서 점 표기 전체 이름 추출
    def _full_name(self, node):
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
        if isinstance(node, ast.Call):
            return self._full_name(node.func)
        return None

    # 토큰 정규화: "a.b.c" → ("a", "a.b.c")
    @staticmethod
    def _split_root(token: str):
        if not token:
            return None, None
        root = token.split(".", 1)[0]
        return root, token

    def visit_Call(self, node):
        fn_token = self._full_name(node.func)
        if fn_token:
            root, full = self._split_root(fn_token)
            # 1) 루트 모듈 화이트리스트에 있으면 채택
            if root in self.EXTERNAL_ROOTS:
                self.external_calls.add(full)
            else:
                # 2) 휴리스틱: qualifier나 메서드명이 네트워크/DB 패턴
                method_name = full.split(".")[-1]
                qualifier = ".".join(full.split(".")[:-1])
                if (method_name in self.METHOD_HINTS and (
                    any(q in qualifier.split(".") for q in self.QUALIFIER_HINTS)
                    or "http" in qualifier or "socket" in qualifier
                )):
                    self.external_calls.add(full)
        self.generic_visit(node)

    def detect(self):
        if not self.tree:
            return []
        self.visit(self.tree)
        return sorted(self.external_calls)
