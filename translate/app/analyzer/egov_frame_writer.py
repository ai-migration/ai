import os

class EgovFrameWriter:
    def __init__(self, base_output_dir="egov_output"):
        self.base_dir = base_output_dir

    def save_code(self, java_code: str, class_name: str, role: str, domain="cop", feature="bbs"):
        """
        주어진 Java 코드를 eGovFramework 표준 경로에 저장합니다.
        class_name을 직접 받아 파일 이름으로 사용하도록 수정되었습니다.
        """
        subdir = self._map_role_to_path(role)
        full_path = os.path.join(
            self.base_dir, "egovframework", "com", domain, feature, subdir
        )
        os.makedirs(full_path, exist_ok=True)

        # 이제 class_name을 그대로 파일명으로 사용합니다.
        file_path = os.path.join(full_path, f"{class_name}.java")

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(java_code)

        print(f"저장 완료: {file_path}")
        return file_path

    def _map_role_to_path(self, role: str) -> str:
        # 역할(role)에 따른 저장 경로 매핑
        if "controller" in role:
            return "web"
        elif "dao" in role:
            # DAO와 Mapper(XML)는 보통 같은 service/impl 경로에 위치
            return "service/impl"
        elif "service" in role:
            return "service"
        # Mapper는 보통 XML 파일이지만, 인터페이스의 경우를 위해 경로를 지정
        elif "mapper" in role:
            return "service/impl"
        else:
            return "common" # 기타(util, config 등)

# 사용 예시
"""
from writer.egov_frame_writer import EgovFrameWriter

# 분석 파이프라인에서 추출한 정보
analyzed_code = 'public class SampleController { ... }'
analyzed_class_name = 'SampleController' #! 분석을 통해 얻은 실제 클래스 이름
analyzed_role = 'controller'

# 개선된 Writer 사용법
writer = EgovFrameWriter()
writer.save_code(
    java_code=analyzed_code,
    class_name=analyzed_class_name, #! 실제 클래스 이름을 전달
    role=analyzed_role
)
"""