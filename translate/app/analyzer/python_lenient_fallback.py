import re
from typing import List, Dict, Tuple

_PY_CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z_]\w*)\s*(?:\([^)]*\))?\s*:\s*$", re.MULTILINE)
_PY_FUNC_RE  = re.compile(r"^\s*def\s+([A-Za-z_]\w*)\s*\([^)]*\)\s*:\s*$", re.MULTILINE)

def extract_outline_from_text(code: str) -> Tuple[List[Dict], List[Dict]]:
    code = code.replace("\r\n","\n").replace("\r","\n")
    classes = [{"name": m.group(1), "type": "ClassDef", "bases": [], "decorators": [], "body": code}
               for m in _PY_CLASS_RE.finditer(code)]
    functions = [{"name": m.group(1), "class": "", "calls": [], "body": ""}
                 for m in _PY_FUNC_RE.finditer(code)]
    return classes, functions