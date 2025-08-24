# sonarQube 분서긍ㄹ 시작만 시켜주는 런처임
# 해당 파일은 시작 역할
# 실제 이슈 데이터는 sonarqube ce가 처리 완료 후, API로 조회해야 한다.

import subprocess
import shutil
print(shutil.which("sonar-scanner"))

project_path = r"C:\Users\User\Desktop\dev\project\java-test"

result = subprocess.run(
    'sonar-scanner',
    cwd=project_path,
    capture_output=True,
    text=True,
    shell=True
)

print("✅ STDOUT:")
print(result.stdout)

print("⚠️ STDERR:")
print(result.stderr)
