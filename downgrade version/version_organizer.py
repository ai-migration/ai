import os
import shutil

#각 구버전 파일들 모으기

# 버전별 원본 폴더 위치 (문서 폴더 기준으로 수정)
BASE_DIR = "C:/Users/User/Documents"
VERSIONS = [
    "2.7.1",
    "3.2.0",
    "3.5.1",
    "3.6.0",
    "3.7.0",
    "3.9.0"
]

# 결과 저장 위치
OUT_BASE = "examples/version"
os.makedirs(OUT_BASE, exist_ok=True)

# 역할 분류 함수
def classify_role(filename):
    name = filename.lower()
    if "controller" in name:
        return "Controller"
    elif "serviceimpl" in name or "impl" in name:
        return "ServiceImpl"
    elif "service" in name:
        return "Service"
    elif "dao" in name:
        return "DAO"
    elif "vo" in name:
        return "VO"
    elif "mapper" in name:
        return "Mapper"
    else:
        return "Other"

# 버전별 복사
for ver in VERSIONS:
    src_root = os.path.join(BASE_DIR, f"egovframework.dev.imp.all-{ver}-source")
    out_dir = os.path.join(OUT_BASE, ver)
    os.makedirs(out_dir, exist_ok=True)

    for root, _, files in os.walk(src_root):
        for file in files:
            if file.endswith(".java"):
                role = classify_role(file)
                new_name = f"{role}__{file}"
                src_file = os.path.join(root, file)
                dst_file = os.path.join(out_dir, new_name)

                try:
                    shutil.copy2(src_file, dst_file)
                except Exception as e:
                    print(f"❌ 복사 실패: {src_file} → {dst_file} | {e}")

    print(f"✅ {ver} 정리 완료 → {out_dir}")
