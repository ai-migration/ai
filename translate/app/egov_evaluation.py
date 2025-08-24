# eGovFrame 정적 규칙 준수 점수(S) 계산기

from __future__ import annotations
import json, re
from dataclasses import dataclass
from typing import Callable, Dict, List, Tuple, Any, Optional

# def _collect_units(data: List[str, Any]) -> List[Dict[str, Any]]:
#     """violations 리포트용: 클래스명 등 메타 포함 수집"""
#     import re as _re
#     units = []
#     for d in data:
#         code = d['code']
#         m = _re.search(r"\b(class|interface)\s+([A-Za-z0-9_]+)", code or "")
#         cls = m.group(2) if m else ""
#         units.append({"group": g, "index": i, "class": cls, "code": code or ""})
#     return units

def _loc(u: Dict[str, Any]) -> str:
    """리포트에서 위치 표현 형식"""
    return f"{u['group']}[{u['index']}]::{u.get('class') or '?'}"

def _any_in(snippets, group_key: str, pattern: str) -> bool:
    prog = re.compile(pattern, re.MULTILINE | re.DOTALL)
    return any(prog.search(s["code"]) for s in snippets if s["group"] == group_key)

def _all_match(data, group_key: str, predicate: Callable[[str], bool]) -> Tuple[bool, int, int]:
    items = [s for s in data if s["group"] == group_key]
    if not items:
        return (False, 0, 0)
    total = len(data)
    passed = sum(1 for s in items if predicate(s["code"]))
    return (passed == total, passed, total)

def _dedup(vios: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """중복 제거(같은 rule/where/missing)"""
    seen = set()
    out = []
    for v in vios:
        key = (v.get("rule"), v.get("where"), v.get("missing"))
        if key in seen:
            continue
        seen.add(key)
        out.append(v)
    return out

@dataclass
class Rule:
    id: str
    description: str
    weight: float
    check: Callable[[], Tuple[bool, Optional[str]]]

def evaluation(data: Dict[str, List]):
    '''
    data = {'controller_egov': [{"group": k, "index": i, "code": code}]}
    '''
    rules: List[Rule] = []
        
    # 1) Controller: egovframework.*.web + @Controller
    def r_C1():
        ok, passed, total = _all_match(
            data, "controller_egov",
            lambda c: ("package egovframework." in c and ".web" in c and "@Controller" in c)
        )
        return ok, f"{passed}/{total} files passed" if total else "no files"

    # 2) Controller: view 반환(String/ModelAndView), ResponseEntity 지양
    def r_C2():
        has_view = _any_in(data, "controller_egov", r"ModelAndView") or _any_in(data, "controller_egov", r"return\s+\"[^\"]+\";")
        has_resp_entity = _any_in(data, "controller_egov", r"\bResponseEntity\b")
        ok = has_view and not has_resp_entity
        return ok, ""

    # 3) PaginationInfo 사용
    def r_C3():
        ok = _any_in(data, "controller_egov", r"\bPaginationInfo\b")
        return ok, ""

    # 4) *.do URL 패턴
    def r_C4():
        ok = _any_in(data, "controller_egov", r"\"/.+\.do\"")
        return ok, ""

    # 5) Service 인터페이스: egovframework.*.service + interface
    def r_S1():
        ok, passed, total = _all_match(
            data, "service_egov",
            lambda c: ("package egovframework." in c and ".service" in c and "interface " in c)
        )
        return ok, f"{passed}/{total} files passed" if total else "no files"

    # 6) ServiceImpl: EgovAbstractServiceImpl 상속 + @Service(\"name\")
    def r_S2():
        ok, passed, total = _all_match(
            data, "serviceimpl_egov",
            lambda c: ("extends EgovAbstractServiceImpl" in c and re.search(r"@Service\(\"[^\"]+\"\)", c) is not None)
        )
        return ok, f"{passed}/{total} files passed" if total else "no files"

    # 7) ServiceImpl: @Resource 주입(+ DAO 사용), @Autowired 회피
    def _check_dao_injection(c: str) -> bool:
        has_resource = "@Resource" in c
        uses_dao = re.search(r"\bDAO\b", c) is not None
        no_autowired = "@Autowired" not in c
        return has_resource and uses_dao and no_autowired
    def r_S3():
        ok, passed, total = _all_match(data, "serviceimpl_egov", _check_dao_injection)
        return ok, f"{passed}/{total} files passed" if total else "no files"

    # 8) Controller는 Service에만 의존(DAO 직접 의존 금지)
    def r_C5():
        ok, passed, total = _all_match(
            data, "controller_egov",
            lambda c: (re.search(r"\b[A-Za-z0-9_]*Service\b", c) is not None) and ("DAO" not in c)
        )
        return ok, f"{passed}/{total} files passed" if total else "no files"

    # 9) VO: Serializable + serialVersionUID(or suppress)
    def _check_vo(c: str) -> bool:
        ok_pkg = "package egovframework." in c
        is_serializable = ("implements Serializable" in c)
        has_serial = ("serialVersionUID" in c) or ('@SuppressWarnings("serial")' in c)
        return ok_pkg and is_serializable and has_serial
    def r_V1():
        ok, passed, total = _all_match(data, "vo_egov", _check_vo)
        return ok, f"{passed}/{total} files passed" if total else "no files"

    # 10) ServiceImpl: Spring Data Repository 직접 의존 회피(DAO 사용)
    def r_S4():
        ok, passed, total = _all_match(
            data, "serviceimpl_egov",
            lambda c: ("Repository" not in c and "DAO" in c)
        )
        return ok, f"{passed}/{total} files passed" if total else "no files"

    # 11) Collectors 사용 시 import 존재
    def _check_collectors_import(c: str) -> bool:
        if "Collectors" in c:
            return "import java.util.stream.Collectors;" in c
        return True
    def r_Q1():
        ok, passed, total = _all_match(data, "serviceimpl_egov", _check_collectors_import)
        return ok, f"{passed}/{total} files passed" if total else "no files"

    # 12) Service 레이어에서 @Autowired 회피(@Resource 선호)
    def r_S5():
        ok, passed, total = _all_match(data, "serviceimpl_egov", lambda c: "@Autowired" not in c)
        return ok, f"{passed}/{total} files passed" if total else "no files"

    if 'controller_egov' in data:
        data = data['controller_egov']
        rules.append(Rule("C1", "Controllers under egovframework.*.web and annotated @Controller", 0.10, r_C1))
        rules.append(Rule("C2", "Controllers return view (String/ModelAndView), not ResponseEntity", 0.05, r_C2))
        rules.append(Rule("C3", "Uses PaginationInfo in controllers for paging", 0.05, r_C3))
        rules.append(Rule("C4", "Controller mappings use *.do pattern", 0.05, r_C4))
        rules.append(Rule("C5", "Controllers depend on *Service types (layering)", 0.05, r_C5))
    elif 'service_egov' in data:
        data = data['service_egov']
        rules.append(Rule("S1", "Service interfaces declared under egovframework.*.service (interface)", 0.10, r_S1))
    elif 'serviceimpl_egov' in data:
        data = data['serviceimpl_egov']
        rules.append(Rule("S2", "ServiceImpl extends EgovAbstractServiceImpl and @Service(\"beanName\")", 0.15, r_S2))
        rules.append(Rule("S3", "ServiceImpl uses DAO via @Resource (avoids @Autowired)", 0.10, r_S3))
        rules.append(Rule("S4", "eGov ServiceImpl avoids Spring Data *Repository and uses *DAO", 0.10, r_S4))
        rules.append(Rule("Q1", "If using Collectors, import java.util.stream.Collectors", 0.05, r_Q1))
        rules.append(Rule("S5", "Avoid @Autowired in eGov service layer (prefer @Resource)", 0.10, r_S5))
    elif 'vo_egov' in data:
        data = data['vo_egov']
        rules.append(Rule("V1", "VOs implement Serializable and define serialVersionUID (or suppress warnings)", 0.10, r_V1))

    # S 계산
    total_weight = sum(r.weight for r in rules)
    score_sum = 0.0
    rule_rows: List[Dict[str, Any]] = []

    for r in rules:
        ok, detail = r.check()
        if ok:
            score_sum += r.weight
        rule_rows.append({
            "id": r.id,
            "description": r.description,
            "weight": r.weight,
            "pass": bool(ok),
            "detail": detail or ""
        })

    S = round(score_sum / total_weight, 4) if total_weight > 0 else 0.0

    return {
        "S": S,
        "rules": rule_rows,
        "summary": {
            "passed_weight": round(score_sum, 4),
            "total_weight": round(total_weight, 4),
            "total_rules": len(rules),
            "passed_rules": sum(1 for r in rule_rows if r["pass"])
        },
        'violations': build_violations(data)
    }

def build_violations(data: List[str, Any]) -> List[Dict[str, str]]:
    """
    코드에서 위반 위치/원인/수정 힌트를 추출한다.
    return: [{rule, title, where, missing, hint}, ...]
    """
    out: List[Dict[str, str]] = []

    # --- ServiceImpl 계열 ---
    for u in [x for x in data if x["group"]=="serviceimpl_egov"]:
        code = u["code"]

        # S2: 상속 + @Service("...")
        missing = []
        if "extends EgovAbstractServiceImpl" not in code:
            missing.append("extends EgovAbstractServiceImpl")
        if not re.search(r'@Service\("([^"]+)"\)', code):
            missing.append('@Service("beanName")')
        if missing:
            out.append({
                "rule":"S2",
                "title":"ServiceImpl extends EgovAbstractServiceImpl and @Service(\"beanName\")",
                "where":_loc(u),
                "missing":", ".join(missing),
                "hint":"클래스 선언부에 extends EgovAbstractServiceImpl 추가 + @Service(\"...\") 명시"
            })

        # S5: @Autowired 금지
        if "@Autowired" in code:
            out.append({
                "rule":"S5",
                "title":"Avoid @Autowired in eGov service layer (prefer @Resource)",
                "where":_loc(u),
                "missing":"@Resource (현재 @Autowired 사용)",
                "hint":"@Autowired 제거 후 @Resource(name=\"...\")로 주입"
            })

        # S3: DAO는 @Resource로 주입(+ @Autowired 없어야 함)
        uses_dao = re.search(r"\bDAO\b", code) is not None
        has_res = "@Resource" in code
        no_auto = "@Autowired" not in code
        if not (uses_dao and has_res and no_auto):
            reasons=[]
            if not uses_dao: reasons.append("no DAO usage")
            if not has_res: reasons.append("missing @Resource")
            if not no_auto: reasons.append("contains @Autowired")
            out.append({
                "rule":"S3",
                "title":"ServiceImpl uses DAO via @Resource (avoids @Autowired)",
                "where":_loc(u),
                "missing":", ".join(reasons) if reasons else "incomplete DAO injection rules",
                "hint":"DAO 필드는 @Resource(name=\"...\")로 주입하고 @Autowired는 지양"
            })

        # Q1: Collectors import
        if "Collectors" in code and "import java.util.stream.Collectors;" not in code:
            out.append({
                "rule":"Q1",
                "title":"If using Collectors, import java.util.stream.Collectors",
                "where":_loc(u),
                "missing":"import java.util.stream.Collectors;",
                "hint":"파일 상단에 import java.util.stream.Collectors; 추가"
            })

        # S4: Repository 직접 의존 회피
        if ("Repository" in code) and ("DAO" not in code):
            out.append({
                "rule":"S4",
                "title":"eGov ServiceImpl avoids Spring Data *Repository and uses *DAO",
                "where":_loc(u),
                "missing":"DAO 사용 없음 (Repository 직접 의존)",
                "hint":"Repository 직접 의존 대신 *DAO 레이어를 사용"
            })

    # --- Controller 계열 ---
    for u in [x for x in data if x["group"]=="controller_egov"]:
        code = u["code"]
        # C1: 패키지/어노테이션
        if ("package egovframework." not in code) or (".web" not in code) or ("@Controller" not in code):
            miss=[]
            if "package egovframework." not in code: miss.append("package egovframework.*.web")
            if ".web" not in code: miss.append("web 패키지 경로")
            if "@Controller" not in code: miss.append("@Controller")
            out.append({
                "rule":"C1",
                "title":"Controllers under egovframework.*.web and annotated @Controller",
                "where":_loc(u),
                "missing":", ".join(miss),
                "hint":"컨트롤러를 egovframework.<proj>.web 패키지에 두고 @Controller 추가"
            })

        # C2: ResponseEntity 지양
        if re.search(r"\bResponseEntity\b", code):
            out.append({
                "rule":"C2",
                "title":"Controllers return view (String/ModelAndView), not ResponseEntity",
                "where":_loc(u),
                "missing":"use JSP view or ModelAndView instead of ResponseEntity",
                "hint":"JSP(String) 또는 ModelAndView 반환으로 변경"
            })

        # C3: PaginationInfo
        if not re.search(r"\bPaginationInfo\b", code):
            out.append({
                "rule":"C3",
                "title":"Uses PaginationInfo in controllers for paging",
                "where":_loc(u),
                "missing":"PaginationInfo 사용 없음",
                "hint":"목록 조회 컨트롤러에 PaginationInfo 적용"
            })

        # C4: *.do 매핑
        if not re.search(r'"/.+\.do"', code):
            out.append({
                "rule":"C4",
                "title":"Controller mappings use *.do pattern",
                "where":_loc(u),
                "missing":"*.do mapping",
                "hint":"@RequestMapping(\"/xxx.do\") 형태로 수정"
            })

        # C5: Service 의존 / DAO 직접 의존 금지
        if re.search(r"\bDAO\b", code):
            out.append({
                "rule":"C5",
                "title":"Controllers depend on *Service types (layering)",
                "where":_loc(u),
                "missing":"Controller에서 DAO 직접 의존",
                "hint":"DAO 의존 제거하고 *Service를 주입/호출"
            })

    # --- VO 계열 ---
    for u in [x for x in data if x["group"]=="vo_egov"]:
        code = u["code"]
        serializable = "implements Serializable" in code
        has_serial = "serialVersionUID" in code or '@SuppressWarnings("serial")' in code
        if not (serializable and has_serial):
            miss=[]
            if not serializable: miss.append("implements Serializable")
            if not has_serial: miss.append("serialVersionUID")
            out.append({
                "rule":"V1",
                "title":"VOs implement Serializable and define serialVersionUID",
                "where":_loc(u),
                "missing":", ".join(miss),
                "hint":"VO는 Serializable 구현 및 serialVersionUID 필드를 선언"
            })

    return _dedup(out)