import re

class JavaAnalyzer:
    def __init__(self, file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            self.lines = f.readlines()
        self.code = "".join(self.lines)

    def extract_class_name(self):
        match = re.search(r'(public\s+)?class\s+(\w+)', self.code)
        return match.group(2) if match else None

    def extract_functions(self):
        functions = []
        class_name = self.extract_class_name()
        if not class_name:
            return []

        i = 0
        while i < len(self.lines):
            line = self.lines[i].strip()

            if line.startswith("@") or re.match(r'(public|private|protected)', line):
                sig_lines = []
                annotations = [] # 어노테이션 저장 리스트
                sig_start = i

                temp_i = i
                body_started = False
                while temp_i < len(self.lines):
                    current_line_stripped = self.lines[temp_i].strip()
                    if current_line_stripped.startswith("@"):
                        annotations.append(current_line_stripped)

                    sig_lines.append(self.lines[temp_i].rstrip())
                    if "{" in current_line_stripped:
                        body_started = True
                        temp_i += 1
                        break
                    temp_i += 1

                if not body_started:
                    i += 1
                    continue

                method_name = self._extract_method_or_constructor_name(sig_lines, class_name)
                if not method_name:
                    i +=1
                    continue

                body_lines = []
                full_sig_text = "".join(sig_lines)
                brace_count = full_sig_text.count("{") - full_sig_text.count("}")

                i = temp_i
                while i < len(self.lines):
                    line_content = self.lines[i]
                    body_lines.append(line_content.rstrip())
                    brace_count += line_content.count("{")
                    brace_count -= line_content.count("}")
                    i += 1
                    if brace_count == 0:
                        break

                full_body = "\n".join(sig_lines + body_lines)
                body = self._extract_core_body(sig_lines + body_lines)

                start_line = sig_start + 1
                end_line = i

                functions.append({
                    "name": method_name,
                    "class": class_name,
                    "calls": self.extract_calls(full_body),
                    "body": body,
                    "full_body": full_body,
                    "annotations": annotations, # 수집된 어노테이션 추가
                    "is_async": False,
                    "line_range": f"L{start_line}-L{end_line}"
                })
            else:
                i += 1
        return functions

    def _extract_method_or_constructor_name(self, sig_lines, class_name):
        full_sig = " ".join(line.strip() for line in sig_lines)
        method_pattern = r'\b(public|private|protected)\b\s+(static\s+)?[\w<>\[\],\s?]+\s+(\w+)\s*\('
        constructor_pattern = rf'\b(public|private|protected)\b\s+({class_name})\s*\('

        method_match = re.search(method_pattern, full_sig)
        if method_match:
            return method_match.group(3)

        constructor_match = re.search(constructor_pattern, full_sig)
        if constructor_match:
            return constructor_match.group(2)

        return None

    def _extract_core_body(self, all_lines):
        body = []
        in_body = False
        for line in all_lines:
            if "{" in line:
                in_body = True

            stripped = line.strip()
            if in_body and stripped and not stripped.startswith('{') and not stripped.startswith('}'):
                body.append(stripped)
        return "\n".join(body).strip('}')

    def extract_calls(self, code):
        return sorted(set(re.findall(r'(\w+)\.', code)))