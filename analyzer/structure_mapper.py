import re

class StructureMapper:
    ROLE_CONTROLLER = "CONTROLLER"
    ROLE_SERVICE_IMPL = "SERVICE_IMPL"
    ROLE_DAO = "DAO"
    ROLE_DTO = "DTO"
    ROLE_ENTITY = "ENTITY"
    ROLE_CONFIG = "CONFIGURATION"
    ROLE_UTIL = "UTIL"
    ROLE_DEFAULT = "COMPONENT"
    # 함수 역할을 위한 상수 추가
    ROLE_CONTROLLER_METHOD = "CONTROLLER_METHOD"

    def infer_class_role(self, class_info: dict) -> dict:
        lang = class_info.get("source_info", {}).get("language")
        if lang == 'python':
            return self._infer_python_class_role(class_info)
        elif lang == 'java':
            return self._infer_java_class_role(class_info)
        return self._get_default_role("Unsupported language")

    # *** 주요 수정 사항: 새로운 메서드 추가 ***
    def infer_standalone_function_role(self, func_info: dict) -> dict:
        """클래스에 속하지 않은 독립 함수의 역할을 추론합니다."""
        decorators = func_info.get("decorators", [])
        # 라우팅 데코레이터가 있으면 컨트롤러 메서드로 판단
        controller_decorators = ["@blueprint.route", "@app.route"]
        if any(marker in deco for deco in decorators for marker in controller_decorators):
            return {
                "type": self.ROLE_CONTROLLER_METHOD,
                "confidence": 0.95,
                "evidence": ["Standalone function has a routing decorator."]
            }
        return self._get_default_role("Standalone function with no clear role.")

    def _infer_python_class_role(self, class_info: dict) -> dict:
        scores = { self.ROLE_CONTROLLER: 0.0, self.ROLE_SERVICE_IMPL: 0.0, self.ROLE_DAO: 0.0, self.ROLE_DTO: 0.0, self.ROLE_ENTITY: 0.0, self.ROLE_CONFIG: 0.0 }
        evidence = {role: [] for role in scores}
        name = (class_info.get("name") or "").lower()
        bases = [b.lower() for b in class_info.get("bases", [])]
        body = (class_info.get("body") or "").lower()
        functions = class_info.get("functions", [])

        # Entity 단서 (SQLAlchemy Model 상속) - 우선순위 높게
        if "model" in bases:
            scores[self.ROLE_ENTITY] += 0.9
            evidence[self.ROLE_ENTITY].append("Inherits from 'Model', indicating it's an SQLAlchemy Entity.")

        # DTO 단서 (Marshmallow Schema 상속) - 우선순위 높게
        if "schema" in bases:
            scores[self.ROLE_DTO] += 0.9
            evidence[self.ROLE_DTO].append("Inherits from 'Schema', indicating it's a Marshmallow DTO/Serializer.")

        # 나머지 휴리스틱 규칙 적용
        controller_decorators = ["@app.route", "@router.get", "@blueprint.route"]
        for func in functions:
            if any(deco in str(func.get("decorators",[])) for deco in controller_decorators):
                scores[self.ROLE_CONTROLLER] += 0.9
                evidence[self.ROLE_CONTROLLER].append("Routing decorator found in a method.")
                break
        if "db.column" in body:
            scores[self.ROLE_ENTITY] += 0.5
            evidence[self.ROLE_ENTITY].append("Contains 'db.Column' definitions.")
        if any(orm_call in body for orm_call in ["session.query", ".query.filter", ".query.get"]):
            scores[self.ROLE_ENTITY] += 0.4
            evidence[self.ROLE_ENTITY].append("ORM method call detected in body.")
        if any(base in str(bases) for base in ["basemodel", "dataclass"]):
             scores[self.ROLE_DTO] += 0.9
             evidence[self.ROLE_DTO].append("Inherits from Pydantic BaseModel or is a dataclass.")
        if name.endswith("config"):
            scores[self.ROLE_CONFIG] += 0.8
            evidence[self.ROLE_CONFIG].append("Class name ends with 'Config'.")
        if name.endswith(("service", "logic", "provider")):
            scores[self.ROLE_SERVICE_IMPL] += 0.4
            evidence[self.ROLE_SERVICE_IMPL].append("Class name ends with 'service' or 'logic'.")

        if not any(s > 0 for s in scores.values()):
            return self._get_default_role(f"No specific evidence found for Python class '{name}'.")

        highest_role = max(scores, key=scores.get)
        confidence = self._normalize_score(scores[highest_role])
        return { "type": highest_role, "confidence": confidence, "evidence": evidence[highest_role] }

    def _infer_java_class_role(self, class_info: dict) -> dict:
        raw_annotations = class_info.get("annotations", [])
        annotations = [ann.lower() for ann in raw_annotations]
        name = (class_info.get("name") or "").lower()
        if "restcontroller" in annotations or "controller" in annotations:
            return {"type": self.ROLE_CONTROLLER, "confidence": 1.0, "evidence": ["@RestController or @Controller annotation found."]}
        elif "service" in annotations:
            return {"type": self.ROLE_SERVICE_IMPL, "confidence": 1.0, "evidence": ["@Service annotation found."]}
        elif "repository" in annotations:
            return {"type": self.ROLE_DAO, "confidence": 1.0, "evidence": ["@Repository annotation found."]}
        elif "entity" in annotations:
            return {"type": self.ROLE_ENTITY, "confidence": 1.0, "evidence": ["@Entity annotation found."]}
        elif "configuration" in annotations:
            return {"type": self.ROLE_CONFIG, "confidence": 1.0, "evidence": ["@Configuration annotation found."]}
        elif "component" in annotations:
             return {"type": self.ROLE_UTIL, "confidence": 0.9, "evidence": ["@Component annotation found."]}
        elif name.endswith("controller"):
            return {"type": self.ROLE_CONTROLLER, "confidence": 0.8, "evidence": ["Class name ends with 'Controller'."]}
        elif name.endswith("serviceimpl") or name.endswith("service"):
            return {"type": self.ROLE_SERVICE_IMPL, "confidence": 0.8, "evidence": ["Class name ends with 'ServiceImpl' or 'Service'."]}
        elif name.endswith("repository") or name.endswith("dao"):
            return {"type": self.ROLE_DAO, "confidence": 0.8, "evidence": ["Class name ends with 'Repository' or 'DAO'."]}
        elif name.endswith(("dto", "vo", "form", "response")):
            return {"type": self.ROLE_DTO, "confidence": 0.9, "evidence": ["Class name ends with 'DTO', 'VO', 'Form', or 'Response'."]}
        elif name.endswith("util"):
             return {"type": self.ROLE_UTIL, "confidence": 0.9, "evidence": ["Class name ends with 'Util'."]}
        else:
            return self._get_default_role(f"No specific annotations or name patterns found for Java class '{name}'.")

    def _normalize_score(self, score: float) -> float:
        if score > 1.0: return 0.99
        if score < 0.1: return 0.1
        return round(score, 2)

    def _get_default_role(self, reason: str) -> dict:
        return {"type": self.ROLE_DEFAULT, "confidence": 0.1, "evidence": [reason]}