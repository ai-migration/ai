import re

class StructureMapper:
    # 역할 상수 정의
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

    def infer_class_role(self, class_info: dict) -> dict:
        """언어에 따라 적절한 클래스 역할 추론 메서드를 호출합니다."""
        lang = class_info.get("source_info", {}).get("language")
        if lang == 'python':
            return self._infer_python_class_role(class_info)
        elif lang == 'java':
            return self._infer_java_class_role(class_info)
        return self._get_default_role("Unsupported language")

    def infer_standalone_function_role(self, func_info: dict) -> dict:
        """(Python용) 클래스에 속하지 않은 독립 함수의 역할을 추론합니다."""
        decorators = func_info.get("decorators", [])
        body = func_info.get("body", "").lower()
        name = func_info.get("name", "").lower()

        # 1. Controller Method 확인
        controller_decorators = ["@blueprint.route", "@app.route"]
        if any(marker in deco for deco in decorators for marker in controller_decorators):
            return {"type": self.ROLE_CONTROLLER_METHOD, "confidence": 0.95, "evidence": ["Standalone function has a routing decorator."]}

        # 2. Configuration/Initialization 함수 확인
        config_keywords = ["app.config", "app.register_", "db.init_app", "create_app"]
        if name.startswith(("create_", "register_")) or any(kw in body for kw in config_keywords):
            return {"type": self.ROLE_CONFIG, "confidence": 0.8, "evidence": ["Function appears to be for app initialization or configuration."]}

        return self._get_default_role("Standalone function with no clear role.")

    def _infer_python_class_role(self, class_info: dict) -> dict:

        scores = {
            self.ROLE_CONTROLLER: 0.0, self.ROLE_SERVICE_IMPL: 0.0, self.ROLE_DAO: 0.0,
            self.ROLE_DTO: 0.0, self.ROLE_ENTITY: 0.0, self.ROLE_CONFIG: 0.0,
            self.ROLE_EXCEPTION: 0.0
        }
        evidence = {role: [] for role in scores}

        name = (class_info.get("name") or "").lower()
        bases = [b.lower() for b in class_info.get("bases", [])]
        body = (class_info.get("body") or "").lower()
        functions = class_info.get("functions", [])

        # 상속 기반 점수 부여
        if "model" in bases or "sqla.model" in bases:
            scores[self.ROLE_ENTITY] += 0.9
            evidence[self.ROLE_ENTITY].append("Inherits from 'Model', indicating it's an ORM Entity.")
        if "schema" in bases or "baseschema" in bases:
            scores[self.ROLE_DTO] += 0.9
            evidence[self.ROLE_DTO].append("Inherits from 'Schema', indicating it's a DTO/Serializer.")
        if any(base in str(bases) for base in ["basemodel", "dataclass"]):
             scores[self.ROLE_DTO] += 0.9
             evidence[self.ROLE_DTO].append("Inherits from Pydantic BaseModel or is a dataclass.")
        if "exception" in bases:
            scores[self.ROLE_EXCEPTION] += 1.0
            evidence[self.ROLE_EXCEPTION].append("Inherits from 'Exception'.")

        # 데코레이터/코드 내용/이름 기반 점수 부여
        controller_decorators = ["@app.route", "@router.get", "@blueprint.route"]
        for func in functions:
            if any(deco in str(func.get("decorators",[])) for deco in controller_decorators):
                scores[self.ROLE_CONTROLLER] += 0.95
                evidence[self.ROLE_CONTROLLER].append("Routing decorator found in a method.")
                break

        if any(orm_call in body for orm_call in ["session.query", ".query.filter", ".execute", "db.session"]):
            scores[self.ROLE_DAO] += 0.7
            evidence[self.ROLE_DAO].append("Database/ORM method call detected in body.")

        if "db.column" in body or "mapped_column" in body:
            scores[self.ROLE_ENTITY] += 0.6
            evidence[self.ROLE_ENTITY].append("Contains ORM 'Column' definitions.")

        # Factory 클래스를 DAO로 판단하는 규칙 추가
        if name.endswith("factory"):
            scores[self.ROLE_DAO] += 0.8
            evidence[self.ROLE_DAO].append("Class name ends with 'Factory', suggesting it creates data models.")

        if name.endswith(("controller", "router")):
            scores[self.ROLE_CONTROLLER] += 0.7
            evidence[self.ROLE_CONTROLLER].append("Class name ends with 'Controller' or 'Router'.")
        if name.endswith("service"):
            scores[self.ROLE_SERVICE_IMPL] += 0.7
            evidence[self.ROLE_SERVICE_IMPL].append("Class name ends with 'Service'.")
        if name.endswith(("dao", "repository")):
            scores[self.ROLE_DAO] += 0.7
            evidence[self.ROLE_DAO].append("Class name ends with 'DAO' or 'Repository'.")
        if name.endswith(("dto", "schema")):
            scores[self.ROLE_DTO] += 0.7
            evidence[self.ROLE_DTO].append("Class name ends with 'DTO' or 'Schema'.")
        if name.endswith("exception"):
            scores[self.ROLE_EXCEPTION] += 0.8
            evidence[self.ROLE_EXCEPTION].append("Class name ends with 'Exception'.")
        if name.endswith("config"):
            scores[self.ROLE_CONFIG] += 0.8
            evidence[self.ROLE_CONFIG].append("Class name ends with 'Config'.")

        if not any(s > 0 for s in scores.values()):
            return self._get_default_role(f"No specific patterns found for Python class '{name}'.")

        highest_role = max(scores, key=scores.get)
        confidence = self._normalize_score(scores[highest_role])
        return { "type": highest_role, "confidence": confidence, "evidence": evidence[highest_role] }

    def _infer_java_class_role(self, class_info: dict) -> dict:
        """
        스코어링 시스템을 사용하여 Java 클래스의 역할을 추론합니다.
        """
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
            scores[self.ROLE_CONTROLLER] += 1.0; evidence[self.ROLE_CONTROLLER].append("@RestController or @Controller.")
        if "service" in annotations:
            scores[self.ROLE_SERVICE_IMPL] += 1.0; evidence[self.ROLE_SERVICE_IMPL].append("@Service.")
        if "repository" in annotations:
            scores[self.ROLE_DAO] += 1.0; evidence[self.ROLE_DAO].append("@Repository.")
        if "entity" in annotations:
            scores[self.ROLE_ENTITY] += 1.0; evidence[self.ROLE_ENTITY].append("@Entity.")
        if "configuration" in annotations:
            scores[self.ROLE_CONFIG] += 1.0; evidence[self.ROLE_CONFIG].append("@Configuration.")
        if "controlleradvice" in annotations:
            scores[self.ROLE_EXCEPTION] += 1.0; evidence[self.ROLE_EXCEPTION].append("@ControllerAdvice.")
        if "component" in annotations:
            scores[self.ROLE_UTIL] += 0.5; evidence[self.ROLE_UTIL].append("@Component.")
        if name.endswith("controller"):
            scores[self.ROLE_CONTROLLER] += 0.8; evidence[self.ROLE_CONTROLLER].append("Name ends with 'Controller'.")
        if name.endswith("serviceimpl"):
            scores[self.ROLE_SERVICE_IMPL] += 0.8; evidence[self.ROLE_SERVICE_IMPL].append("Name ends with 'ServiceImpl'.")
        elif name.endswith("service"):
            if declaration_type == "InterfaceDeclaration":
                scores[self.ROLE_SERVICE] += 0.9; evidence[self.ROLE_SERVICE].append("Interface name ends with 'Service'.")
            else:
                scores[self.ROLE_SERVICE_IMPL] += 0.7; evidence[self.ROLE_SERVICE_IMPL].append("Class name ends with 'Service'.")
        if name.endswith("repository") or name.endswith("dao"):
            scores[self.ROLE_DAO] += 0.8; evidence[self.ROLE_DAO].append("Name ends with 'Repository' or 'DAO'.")
        if name.endswith(("dto", "vo", "form", "response", "data")):
            scores[self.ROLE_DTO] += 0.9; evidence[self.ROLE_DTO].append("Name ends with 'DTO', 'VO', 'Form', 'Response', or 'Data'.")
        if name.endswith("exception"):
            scores[self.ROLE_EXCEPTION] += 0.9; evidence[self.ROLE_EXCEPTION].append("Name ends with 'Exception'.")
        if name.endswith("config"):
            scores[self.ROLE_CONFIG] += 0.8; evidence[self.ROLE_CONFIG].append("Name ends with 'Config'.")
        if name.endswith("util"):
             scores[self.ROLE_UTIL] += 0.7; evidence[self.ROLE_UTIL].append("Name ends with 'Util'.")

        if not any(s > 0 for s in scores.values()):
            return self._get_default_role(f"No specific patterns for Java class '{name}'.")
        highest_role = max(scores, key=scores.get)
        confidence = self._normalize_score(scores[highest_role])
        return {"type": highest_role, "confidence": confidence, "evidence": evidence[highest_role]}

    def _normalize_score(self, score: float) -> float:
        """점수를 0.1 ~ 0.99 사이의 신뢰도로 변환합니다."""
        if score > 1.0: return 0.99
        if score < 0.1: return 0.1
        return round(score, 2)

    def _get_default_role(self, reason: str) -> dict:
        """기본 역할을 반환합니다."""
        return {"type": self.ROLE_DEFAULT, "confidence": 0.1, "evidence": [reason]}