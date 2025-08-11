# analyzer/structure_mapper.py
import re

class StructureMapper:
    # === 기존 상수 유지 ===
    ROLE_CONTROLLER = "CONTROLLER"
    ROLE_SERVICE = "SERVICE"
    ROLE_SERVICE_IMPL = "SERVICEIMPL"
    ROLE_DAO = "DAO"
    ROLE_DTO = "DTO"
    ROLE_ENTITY = "ENTITY"
    ROLE_CONFIG = "CONFIGURATION"
    ROLE_EXCEPTION = "EXCEPTION"
    ROLE_UTIL = "UTIL"
    ROLE_DEFAULT = "UTIL"
    ROLE_CONTROLLER_METHOD = "CONTROLLER_METHOD"

    # ---- Django/DRF 힌트 ----
    _DJANGO_VIEW_BASES = {
        # PythonAnalyzer가 클래스 bases 끝 토큰만 넣는 경우를 고려해 소문자로 비교
        "view", "templateview", "listview", "detailview",
        "createview", "updateview", "deleteview",
        "apiview", "genericapiview", "viewset"
    }
    _DJANGO_VIEW_DECOS = {
        "api_view", "require_http_methods", "csrf_exempt",
        "login_required", "permission_required",
    }
    _DAO_HINTS_BODY = ("session.query", ".query(", ".raw(", "execute(", "db.session", "cursor.execute(")
    _MANAGER_HINTS = ("objects.", "manager", "queryset")
    _IGNORE_SUBSTR = ("/tests/", "/migrations/", "/migrations_test_apps/", "/docs/")

    def infer_class_role(self, class_info: dict) -> dict:
        lang = class_info.get("source_info", {}).get("language")
        if lang == 'python':
            return self._infer_python_class_role(class_info)
        elif lang == 'java':
            return self._infer_java_class_role(class_info)
        return self._get_default_role("Unsupported language")

    def infer_standalone_function_role(self, func_info: dict) -> dict:
        """클래스에 속하지 않은 함수(Flask/Django 함수형 뷰 포함) 역할 추론"""
        decorators = [str(d).lower() for d in func_info.get("decorators", [])]
        body = (func_info.get("body") or "").lower()
        name = (func_info.get("name") or "").lower()
        rel = ((func_info.get("source_info") or {}).get("rel_path") or "").replace("\\", "/").lower()

        # 노이즈 경로 무시
        if any(s in rel for s in self._IGNORE_SUBSTR):
            return self._get_default_role("Ignored path (tests/migrations/docs).")

        # Django/DRF 함수형 뷰: 데코레이터 또는 views.py 위치
        if "/views/" in rel or rel.endswith("/views.py"):
            return {"type": self.ROLE_CONTROLLER_METHOD, "confidence": 0.95,
                    "evidence": ["views.py (function-based view)"]}

        if any(d.lstrip("@").split("(")[0] in self._DJANGO_VIEW_DECOS for d in decorators):
            return {"type": self.ROLE_CONTROLLER_METHOD, "confidence": 0.95,
                    "evidence": ["Django/DRF view decorator"]}

        # 앱 초기화/설정
        if rel.endswith("/urls.py") or "/settings/" in rel \
           or any(k in body for k in ("app.config", "app.register_", "db.init_app", "create_app", "include(")):
            return {"type": self.ROLE_CONFIG, "confidence": 0.8,
                    "evidence": ["App init/config or urls/settings path"]}

        # 관례적 서비스 위치
        if "/service/" in rel or "/services/" in rel:
            return {"type": self.ROLE_SERVICE_IMPL, "confidence": 0.7,
                    "evidence": ["Service naming/path"]}

        return self._get_default_role("Standalone function with no clear role.")

    # ---------------------- Python ----------------------
    def _infer_python_class_role(self, class_info: dict) -> dict:
        scores = {
            self.ROLE_CONTROLLER: 0.0, self.ROLE_SERVICE_IMPL: 0.0, self.ROLE_DAO: 0.0,
            self.ROLE_DTO: 0.0, self.ROLE_ENTITY: 0.0, self.ROLE_CONFIG: 0.0,
            self.ROLE_EXCEPTION: 0.0, self.ROLE_UTIL: 0.0
        }
        evidence = {role: [] for role in scores}

        name = (class_info.get("name") or "").lower()
        bases = [b.lower() for b in (class_info.get("bases") or [])]
        body = (class_info.get("body") or "").lower()
        functions = class_info.get("functions", [])  # analyze_python에서 주입됨
        rel = ((class_info.get("source_info") or {}).get("rel_path") or "").replace("\\", "/").lower()

        # 무시 경로
        if any(s in rel for s in self._IGNORE_SUBSTR):
            return self._get_default_role("Ignored path (tests/migrations/docs).")

        # === ENTITY: Django model ===
        if "model" in bases or "/models/" in rel or rel.endswith("/models.py"):
            scores[self.ROLE_ENTITY] += 1.0
            evidence[self.ROLE_ENTITY].append("Django model path/base")

        # === CONTROLLER: class-based views ===
        if any(b in self._DJANGO_VIEW_BASES for b in bases) or "/views/" in rel or rel.endswith("/views.py"):
            scores[self.ROLE_CONTROLLER] += 1.0
            evidence[self.ROLE_CONTROLLER].append("Django class-based view or views.py")

        # 메서드에 라우팅/뷰 데코레이터가 있으면 Controller 가중치
        controller_decorators = {"@app.route", "@blueprint.route", "@router.get"} \
                                | {f"@{d}" for d in self._DJANGO_VIEW_DECOS}
        for fn in functions:
            decos = [str(d).lower() for d in fn.get("decorators", [])]
            if any(mark in f"@{deco}" for deco in decos for mark in controller_decorators):
                scores[self.ROLE_CONTROLLER] += 0.95
                evidence[self.ROLE_CONTROLLER].append("Routing/view decorator in method")
                break

        # === DAO: ORM/Manager/Raw SQL/Repository 명명/경로 ===
        if any(h in body for h in self._DAO_HINTS_BODY):
            scores[self.ROLE_DAO] += 0.7; evidence[self.ROLE_DAO].append("DB/ORM call in body")
        if any(s in name for s in ("repository", "dao")) or "/repository/" in rel or "/repositories/" in rel or "/dao/" in rel:
            scores[self.ROLE_DAO] += 0.8; evidence[self.ROLE_DAO].append("Repository/DAO naming or path")
        if any(h in body for h in self._MANAGER_HINTS):
            scores[self.ROLE_DAO] += 0.4; evidence[self.ROLE_DAO].append("Manager/QuerySet hint")

        # === DTO: serializers/forms/dataclass/pydantic ===
        if "/serializers/" in rel or rel.endswith("/serializers.py"):
            scores[self.ROLE_DTO] += 0.9; evidence[self.ROLE_DTO].append("DRF serializer path")
        if "/forms/" in rel or rel.endswith("/forms.py") or "form" in bases or "modelform" in bases:
            scores[self.ROLE_DTO] += 0.8; evidence[self.ROLE_DTO].append("Django form path/base")
        if any(base in bases for base in ("basemodel", "dataclass", "schema", "baseschema")):
            scores[self.ROLE_DTO] += 0.7; evidence[self.ROLE_DTO].append("Pydantic/dataclass/schema base")

        # === CONFIG: settings/apps/admin/urls/asgi/wsgi/middleware/권한 ===
        if any(seg in rel for seg in ("/settings/", "/apps.py", "/admin.py", "/urls.py", "/asgi.py", "/wsgi.py")):
            scores[self.ROLE_CONFIG] += 0.9; evidence[self.ROLE_CONFIG].append("Django config/admin/urls/asgi/wsgi")
        if "middleware" in rel:
            scores[self.ROLE_CONFIG] += 0.7; evidence[self.ROLE_CONFIG].append("Middleware path")
        if any(seg in rel for seg in ("/auth/", "/permission")):
            scores[self.ROLE_CONFIG] += 0.4; evidence[self.ROLE_CONFIG].append("Auth/permission path")

        # === SERVICE: 관례적 service 디렉토리/이름 ===
        if "/service/" in rel or "/services/" in rel or name.endswith("service"):
            scores[self.ROLE_SERVICE_IMPL] += 0.7; evidence[self.ROLE_SERVICE_IMPL].append("Service naming/path")

        # === EXCEPTION/UTIL 보조 규칙 ===
        if name.endswith("exception") or "exception" in bases:
            scores[self.ROLE_EXCEPTION] += 0.8; evidence[self.ROLE_EXCEPTION].append("Exception naming/base")
        if name.endswith("config"):
            scores[self.ROLE_CONFIG] += 0.5; evidence[self.ROLE_CONFIG].append("Name ends with 'Config'")
        if name.endswith("util") or "/utils/" in rel or "/helpers/" in rel:
            scores[self.ROLE_UTIL] += 0.5; evidence[self.ROLE_UTIL].append("Utility naming/path")

        if not any(s > 0 for s in scores.values()):
            return self._get_default_role(f"No specific patterns found for Python class '{name}'.")

        highest_role = max(scores, key=scores.get)
        return {"type": highest_role, "confidence": self._normalize_score(scores[highest_role]), "evidence": evidence[highest_role]}

    # ---------------------- Java ----------------------
    def _infer_java_class_role(self, class_info: dict) -> dict:
        scores = {
            self.ROLE_CONTROLLER: 0.0, self.ROLE_SERVICE: 0.0, self.ROLE_SERVICE_IMPL: 0.0,
            self.ROLE_DAO: 0.0, self.ROLE_DTO: 0.0, self.ROLE_ENTITY: 0.0,
            self.ROLE_CONFIG: 0.0, self.ROLE_EXCEPTION: 0.0, self.ROLE_UTIL: 0.0
        }
        evidence = {role: [] for role in scores}
        annotations = [ann.lower() for ann in class_info.get("annotations", [])]
        name = (class_info.get("name") or "").lower()
        declaration_type = class_info.get("type", "")

        if "restcontroller" in annotations or "controller" in annotations:
            scores[self.ROLE_CONTROLLER] += 1.0; evidence[self.ROLE_CONTROLLER].append("@RestController/@Controller")
        if "service" in annotations:
            scores[self.ROLE_SERVICE_IMPL] += 1.0; evidence[self.ROLE_SERVICE_IMPL].append("@Service")
        if "repository" in annotations:
            scores[self.ROLE_DAO] += 1.0; evidence[self.ROLE_DAO].append("@Repository")
        if "entity" in annotations:
            scores[self.ROLE_ENTITY] += 1.0; evidence[self.ROLE_ENTITY].append("@Entity")
        if "configuration" in annotations:
            scores[self.ROLE_CONFIG] += 1.0; evidence[self.ROLE_CONFIG].append("@Configuration")
        if "controlleradvice" in annotations:
            scores[self.ROLE_EXCEPTION] += 1.0; evidence[self.ROLE_EXCEPTION].append("@ControllerAdvice")
        if "component" in annotations:
            scores[self.ROLE_UTIL] += 0.5; evidence[self.ROLE_UTIL].append("@Component")

        if name.endswith("controller"):
            scores[self.ROLE_CONTROLLER] += 0.8; evidence[self.ROLE_CONTROLLER].append("Name ends with 'Controller'")
        if name.endswith("serviceimpl"):
            scores[self.ROLE_SERVICE_IMPL] += 0.8; evidence[self.ROLE_SERVICE_IMPL].append("Name ends with 'ServiceImpl'")
        elif name.endswith("service"):
            if declaration_type == "InterfaceDeclaration":
                scores[self.ROLE_SERVICE] += 0.9; evidence[self.ROLE_SERVICE].append("Interface ends with 'Service'")
            else:
                scores[self.ROLE_SERVICE_IMPL] += 0.7; evidence[self.ROLE_SERVICE_IMPL].append("Class ends with 'Service'")
        if name.endswith(("repository", "dao")):
            scores[self.ROLE_DAO] += 0.8; evidence[self.ROLE_DAO].append("Ends with 'Repository'/'DAO'")
        if name.endswith(("dto", "vo", "form", "response", "data")):
            scores[self.ROLE_DTO] += 0.9; evidence[self.ROLE_DTO].append("Ends with DTO/VO/Form/Response/Data")
        if name.endswith("exception"):
            scores[self.ROLE_EXCEPTION] += 0.9; evidence[self.ROLE_EXCEPTION].append("Ends with 'Exception'")
        if name.endswith("config"):
            scores[self.ROLE_CONFIG] += 0.8; evidence[self.ROLE_CONFIG].append("Ends with 'Config'")
        if name.endswith("util"):
            scores[self.ROLE_UTIL] += 0.7; evidence[self.ROLE_UTIL].append("Ends with 'Util'")

        if not any(s > 0 for s in scores.values()):
            return self._get_default_role(f"No specific patterns for Java class '{name}'.")
        highest_role = max(scores, key=scores.get)
        return {"type": highest_role, "confidence": self._normalize_score(scores[highest_role]), "evidence": evidence[highest_role]}

    # ---------------------- 공통 ----------------------
    def _normalize_score(self, score: float) -> float:
        if score > 1.0: return 0.99
        if score < 0.1: return 0.1
        return round(score, 2)

    def _get_default_role(self, reason: str) -> dict:
        return {"type": self.ROLE_DEFAULT, "confidence": 0.1, "evidence": [reason]}
