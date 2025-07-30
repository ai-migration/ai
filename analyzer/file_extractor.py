import zipfile, os
from typing import List, Tuple

SUPPORTED_LANGUAGES = {
    '.py': 'python',
    '.java': 'java',
    '.js': 'javascript',
    '.xml': 'xml',
    '.json': 'json',
    '.yml': 'yaml',
    '.yaml': 'yaml',
    '.sql': 'sql'
}

class FileExtractor:
    def __init__(self, zip_path: str, extract_dir: str = "extracted_files"):
        self.zip_path = zip_path
        self.extract_dir = extract_dir

    def extract_zip(self) -> str:
        if not os.path.exists(self.extract_dir):
            os.makedirs(self.extract_dir)
        with zipfile.ZipFile(self.zip_path, "r") as zip_ref:
            zip_ref.extractall(self.extract_dir)
        return self.extract_dir

    def find_supported_code_files(self) -> List[Tuple[str, str]]:
        """
        Returns list of (filepath, language)
        """
        result = []
        for root, _, files in os.walk(self.extract_dir):
            for file in files:
                ext = os.path.splitext(file)[-1].lower()
                if ext in SUPPORTED_LANGUAGES:
                    full_path = os.path.join(root, file)
                    lang = SUPPORTED_LANGUAGES[ext]
                    result.append((full_path, lang))
        return result


# 사용 예시
"""

# test_extract.py
from file_extractor import FileExtractor

extractor = FileExtractor("samples/project.zip")
extractor.extract_zip()
code_files = extractor.find_supported_code_files()

for path, lang in code_files:
    print(f"🧩 {lang.upper()} 파일: {path}")

"""