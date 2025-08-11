from dataclasses import dataclass

@dataclass
class ToTranslator:
    id: int
    user_id: int
    file_path: str
    input_egov_frame_ver: str
    output_egov_frame_ver: str
    is_test_code: bool
    conversion_type: str

@dataclass
class ToAuditor:
    id: int