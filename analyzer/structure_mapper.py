class StructureMapper:
    def infer_role(self, func_info: dict, class_info: dict = None):
        lang = func_info.get("language")
        body = (func_info.get("body") or "").lower()
        name = (func_info.get("name") or "").lower()

        # --- Python 역할 추론 ---
        if lang == 'python':
            # 참고: 현재 파이썬 분석기는 데코레이터를 추출하지 않으므로, 이 부분은 향후 확장용입니다.
            decorators = [d.lower() for d in func_info.get("decorators", [])]
            if "print(" in body and "input(" not in body:
                return "controller"
            if any("route" in d or "router." in d for d in decorators):
                return "controller"
            if any(kw in body for kw in ["db.", "query", "read_sql", "execute", "session.query"]):
                return "dao"
            if any(kw in body for kw in ["jwt", "session", "login_required"]):
                return "security"
            if any(kw in body for kw in ["raise", "try:", "@app.errorhandler", "@exception_handler"]):
                return "exception_handler"
            if any(kw in body for kw in ["request.files", "multipart", "file.stream"]) or "upload" in name:
                return "file_upload"
            return "service" # Python 기본값

        # --- Java 역할 추론 ---
        if lang == 'java':
            func_annotations = func_info.get("annotations", [])
            class_annotations = class_info.get("annotations", []) if class_info else []
            all_annotations = func_annotations + class_annotations
            class_name = (func_info.get("class") or "").lower()

            # 1. 어노테이션 기반 (가장 정확)
            for ann in all_annotations:
                if any(ctrl in ann for ctrl in ["@RestController", "@Controller"]):
                    return "controller"
                if "@Service" in ann:
                    return "service"
                if "@Repository" in ann:
                    return "dao"
                if any(mapping in ann for mapping in ["@GetMapping", "@PostMapping", "@PutMapping", "@DeleteMapping", "@PatchMapping"]):
                    return "controller"
                if "@ExceptionHandler" in ann:
                    return "exception_handler"
                if "@Bean" in ann:
                    return "config"

            # 2. 클래스 이름 기반
            if "controller" in class_name:
                return "controller"
            if "service" in class_name:
                return "service"
            if any(dao in class_name for dao in ["repository", "dao", "mapper"]):
                return "dao"
            if "config" in class_name:
                return "config"

        # 모든 규칙에 해당하지 않을 경우의 최종 기본값
        return "service"