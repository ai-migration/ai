import os

class EgovFrameWriter:
    def __init__(self, base_output_dir="egov_output"):
        self.base_dir = base_output_dir

    def save_code(self, java_code: str, func_name: str, role: str, domain="cop", feature="bbs"):
        subdir = self._map_role_to_path(role)
        full_path = os.path.join(
            self.base_dir, "egovframework", "com", domain, feature, subdir
        )
        os.makedirs(full_path, exist_ok=True)

        class_name = self._convert_func_to_class(func_name, role)
        file_path = os.path.join(full_path, f"{class_name}.java")

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(java_code)

        print(f"저장 완료: {file_path}")
        return file_path

    def _map_role_to_path(self, role: str) -> str:
        if "controller" in role:
            return "web"
        elif "dao" in role:
            return "service/impl"
        elif "service" in role:
            return "service"
        elif "mapper" in role:
            return "mapper"
        else:
            return "common"

    def _convert_func_to_class(self, name: str, role: str) -> str:
        name = name[0].upper() + name[1:]
        suffix = {
            "controller": "Controller",
            "service": "Service",
            "dao": "DAO"
        }
        for key, suf in suffix.items():
            if key in role:
                return f"{name}{suf}"
        return f"{name}Util"

# 사용 예시
"""
from writer.egov_frame_writer import EgovFrameWriter

writer = EgovFrameWriter()
writer.save_code(java_code="public class Test {}", func_name="greet", role="controller")

"""