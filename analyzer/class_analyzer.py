import re

class ClassAnalyzer:
    def __init__(self, file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            self.code = f.read()

    def analyze(self):
        class_info = self._extract_class_declaration()
        if not class_info:
            return None

        class_info['fields'] = self._extract_fields()
        return class_info

    def _extract_class_declaration(self):
        # 클래스 선언부 (어노테이션 포함) 추출
        class_decl_match = re.search(
            r'((?:@\w+\s*?)+)?\s*'  # Annotations
            r'(public\s+)?(class|interface|enum)\s+(\w+)'  # public class/interface/enum ClassName
            r'(\s+extends\s+\w+)?'  # extends Parent
            r'(\s+implements\s+[\w,\s]+)?',  # implements Interfaces
            self.code, re.DOTALL
        )

        if not class_decl_match:
            return None

        annotations_str, _, class_type, class_name, extends, implements = class_decl_match.groups()

        annotations = []
        if annotations_str:
            annotations = [ann.strip() for ann in annotations_str.strip().split('\n')]


        return {
            "name": class_name,
            "type": class_type,
            "extends": (extends or "").replace("extends", "").strip() or None,
            "implements": (implements or "").replace("implements", "").strip() or None,
            "annotations": annotations,
        }

    def _extract_fields(self):
        fields = []
        # 필드 선언 정규식 (어노테이션, 접근제어자, 타입, 이름)
        field_pattern = re.compile(
            r'((?:@\w+\(.*\)\s*|@\w+\s*)+)?'  # Annotations
            r'\s*(private|public|protected)?\s*(static\s+)?(final\s+)?'  # Modifiers
            r'([\w<>\[\],\?]+)\s+'  # Type
            r'(\w+);',  # Name
            re.DOTALL
        )

        matches = field_pattern.finditer(self.code)

        for match in matches:
            annotations_str, _, _, _, field_type, field_name = match.groups()

            field_annotations = []
            if annotations_str:
                field_annotations = [ann.strip() for ann in annotations_str.strip().split('\n')]

            fields.append({
                "name": field_name,
                "type": field_type.strip(),
                "annotations": field_annotations
            })
        return fields