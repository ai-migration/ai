import subprocess
# import shutil
# print(shutil.which("sonar-scanner"))

project_path = r"C:\Users\User\Desktop\dev\project\python-test"

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
