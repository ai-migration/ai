# analyzer/external_usage_detector.py
import ast
import logging

logger = logging.getLogger(__name__)

class ExternalUsageDetector(ast.NodeVisitor):
    """
    소스 코드에서 '외부 호출'로 볼 가능성이 높은 호출을 식별자 토큰으로 추출.
    반환 형식: 정렬된 문자열 리스트 (예: ["httpx.get", "sqlalchemy.create_engine", "uvicorn.run"])
    """
    EXTERNAL_ROOTS = {
        # HTTP/네트워킹
        "requests", "httpx", "aiohttp", "urllib", "http", "websockets",
        # FastAPI/Starlette 런타임(런/서버 구동 등)
        "uvicorn", "starlette",
        # DB/ORM/드라이버
        "sqlalchemy", "psycopg2", "asyncpg", "aiomysql", "pymysql", "sqlite3", "mysql",
        "pymongo", "motor", "redis",
        # 메시징/스트리밍
        "confluent_kafka", "kafka", "pika",
        # RPC/Observability
        "grpc", "sentry_sdk",
        # 기타 클라이언트 SDK
        "boto3", "botocore",
    }

    QUALIFIER_HINTS = {"cursor", "connection", "session", "engine", "client", "resource", "producer", "consumer", "channel"}
    METHOD_HINTS = {"execute", "fetchone", "fetchall", "query", "get", "post", "put", "delete",
                    "send", "receive", "publish", "subscribe", "connect", "run"}

    def __init__(self, source_code: str):
        self.external_calls = set()
        try:
            self.tree = ast.parse(source_code)
        except Exception as e:
            logger.warning(f"[ExternalUsageDetector] Parse failed: {e}")
            self.tree = None

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
            if root in self.EXTERNAL_ROOTS:
                self.external_calls.add(full)
            else:
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
