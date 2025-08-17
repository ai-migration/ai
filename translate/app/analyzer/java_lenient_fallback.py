import re
from typing import List, Dict

_JAVA_CLASS_RE  = re.compile(
    r"(?P<ann>(?:@\w+(?:\([^)]*\))?\s*)*)\s*(?P<kind>class|interface|enum)\s+(?P<name>[A-Za-z_]\w*)",
    re.MULTILINE
)
_JAVA_ANN_RE = re.compile(r"@([A-Za-z_]\w+)")

def extract_classes_lenient_from_text(code: str) -> List[Dict]:
    code = code.replace("\r\n","\n").replace("\r","\n")
    classes: List[Dict] = []
    for m in _JAVA_CLASS_RE.finditer(code):
        ann_block = m.group("ann") or ""
        annotations = _JAVA_ANN_RE.findall(ann_block)
        kind = m.group("kind"); name = m.group("name")
        classes.append({
            "name": name,
            "type": "ClassDeclaration" if kind=="class" else ("InterfaceDeclaration" if kind=="interface" else "EnumDeclaration"),
            "description": "",
            "annotations": annotations,
            "body": code,  # 다운스트림 스키마에 맞춰 원문 보존
        })
    return classes