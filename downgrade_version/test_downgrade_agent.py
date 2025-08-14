from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
import glob
import os

# --- 루트 고정: 어디서 실행해도 루트 기준 경로가 되게 함 ---
ROOT = Path(__file__).resolve().parents[1]   # EGOV_RAG_DOWNGRADE
os.chdir(ROOT)

# 패키지 import (scripts → downgrade_version)
from downgrade_version.version_downgrade_agent import (
    DowngradeState,
    retrieve_examples,
    convert_code,
    finalize,
    save_outputs,
    build_ir,
    dump_ir_to_file,
)

# ==== 기본 검색 루트 ====
# >>> 폴더명을 최종 배치에 맞춰 사용하세요. (권장: downgrade_version)
DEFAULT_SEARCH_DIRS = [
    "downgrade_version",                 # ← 여기 맞춤
    "examples/version_downgrade/4.x",
    "examples/version_downgrade",
]


def parse_args(root: Path) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Down-convert 4.x Java to legacy eGovFrame versions (multi-target)."
    )
    p.add_argument(
        "--input",
        help=r"자바 파일/디렉터리/글롭 패턴 (예: version_downgrade\*.java). 미지정 시 자동 스캔/선택.",
        default=None,
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="--input 없이 실행 시: 자동 스캔된 모든 파일을 일괄 변환(질문 없이).",
    )
    p.add_argument(
        "--output_dir",
        default=str(root / "converted_downgrade"),
        help="코드 결과 저장 디렉터리 (기본: converted_downgrade)",
    )
    p.add_argument(
        "--versions",
        nargs="+",
        default=["2.7.1", "3.2.0", "3.5.1", "3.6.0", "3.7.0", "3.9.0"],
        help="타겟 구버전 목록 (공백 구분)",
    )
    # JSON IR 저장 옵션
    p.add_argument(
        "--emit_json",
        action="store_true",
        help="변환 결과와 함께 IR(JSON)도 저장합니다.",
    )
    p.add_argument(
        "--json_dir",
        default=str(root / "converted_downgrade_ir"),
        help="IR(JSON) 저장 디렉터리 (기본: converted_downgrade_ir)",
    )
    # IR를 버전별 파일로 쪼갤지 여부 (선택)
    p.add_argument(
        "--split_ir",
        action="store_true",
        help="IR을 입력 하나당 1개가 아니라, 버전별로 쪼개 저장합니다.",
    )
    return p.parse_args()

def _to_abs(root: Path, p: Path) -> Path:
    return p if p.is_absolute() else (root / p).resolve()

def _scan_candidates(root: Path) -> List[Path]:
    files: List[Path] = []
    for rel in DEFAULT_SEARCH_DIRS:
        base = _to_abs(root, Path(rel))
        if base.exists():
            if base.is_file() and base.suffix.lower() == ".java":
                files.append(base)
            else:
                files.extend(sorted(base.rglob("*.java")))
    # dedup
    seen = set()
    uniq: List[Path] = []
    for f in files:
        if f not in seen:
            uniq.append(f)
            seen.add(f)
    return uniq

def _choose(files: List[Path]) -> List[Path]:
    print("\n[SELECT] 변환할 파일을 선택하세요:")
    for i, f in enumerate(files, 1):
        print(f"  {i:>2}. {f}")
    print("입력 예시) 1,3,5  혹은  2-6  혹은  all")
    s = input("선택: ").strip().lower()
    if s in ("all", "a", "*"):
        return files
    picks: List[int] = []
    for tok in s.replace(" ", "").split(","):
        if "-" in tok:
            a, b = tok.split("-", 1)
            if a.isdigit() and b.isdigit():
                picks.extend(range(int(a), int(b) + 1))
        elif tok.isdigit():
            picks.append(int(tok))
    chosen: List[Path] = []
    for idx in picks:
        if 1 <= idx <= len(files):
            chosen.append(files[idx - 1])
    if not chosen:
        print("[INFO] 올바른 선택이 없어 취소되었습니다.")
    return chosen

def iter_inputs(root: Path, user_input: Optional[str], use_all: bool) -> List[Path]:
    # 1) --input 제공
    if user_input:
        p = Path(user_input)
        # 글롭 패턴 (예: version_downgrade\*.java)
        if any(ch in str(p) for ch in ["*", "?", "[", "]"]):
            pat = str(p).replace("\\", "/")
            files = [f for f in root.glob(pat) if f.is_file() and f.suffix.lower() == ".java"]
            if not files:
                raise FileNotFoundError(f"글롭과 일치하는 파일이 없습니다: {user_input}")
            return files
        # 파일/폴더
        p = _to_abs(root, p)
        if p.is_file():
            if p.suffix.lower() != ".java":
                raise ValueError(f"자바 파일이 아닙니다: {p}")
            return [p]
        if p.is_dir():
            files = sorted(p.rglob("*.java"))
            if not files:
                raise FileNotFoundError(f"디렉터리에 .java 파일이 없습니다: {p}")
            return files
        raise FileNotFoundError(p)

    # 2) --input 미지정 → 자동 스캔
    candidates = _scan_candidates(root)
    if not candidates:
        raise FileNotFoundError(
            "자동 스캔에서 .java 파일을 찾지 못했습니다.\n"
            f"검색 경로: {', '.join(DEFAULT_SEARCH_DIRS)}\n"
            "옵션 예) --input version_downgrade  또는  --input \"version_downgrade\\*.java\""
        )
    if use_all:
        return candidates
    # 선택 모드
    chosen = _choose(candidates)
    if not chosen:
        raise SystemExit(0)
    return chosen

def main() -> None:
    load_dotenv()
    ROOT = Path(__file__).resolve().parents[1]
    args = parse_args(ROOT)

    outdir = _to_abs(ROOT, Path(args.output_dir))
    outdir.mkdir(parents=True, exist_ok=True)

    jsondir = _to_abs(ROOT, Path(args.json_dir))
    if args.emit_json:
        jsondir.mkdir(parents=True, exist_ok=True)

    files = iter_inputs(ROOT, args.input, args.all)

    print(f"[INFO] Output dir     : {outdir}")
    print(f"[INFO] Input files    : {len(files)}개")
    print(f"[INFO] Target versions: {', '.join(args.versions)}")

    saved_all: List[Path] = []
    saved_json: List[Path] = []

    for fp in files:
        code = fp.read_text(encoding="utf-8")
        state: DowngradeState = {
            "input_code": code,
            "input_filename": str(fp),
            "output_dir": str(outdir),
            "target_versions": list(args.versions),
            "retrieved": [],
            "results": {},
            "report": {},
        }

        # 순차 실행
        state = retrieve_examples(state)
        state = convert_code(state)
        state = finalize(state)

        # 코드 저장 (버전별 하위 폴더는 save_outputs가 처리)
        save_outputs(state)

        # 저장된 경로 로깅(상위 outdir에서도 파일명으로 한 벌 저장하고 싶으면 추가)
        base = Path(fp).stem
        for ver, converted_code in state["results"].items():
            out_file = outdir / f"{base}_{ver}.java"
            out_file.write_text(converted_code, encoding="utf-8")
            saved_all.append(out_file)
            print(f"[SAVED] {out_file}")

        # IR 저장
        if args.emit_json:
            if args.split_ir:
                # 버전별 IR로 쪼개 저장
                for ver, converted_code in state["results"].items():
                    one = dict(state)  # 얕은 복사
                    one["results"] = {ver: converted_code}
                    ir = build_ir(one)  # 해당 버전만 담긴 IR
                    ir_path = jsondir / f"{base}_{ver}.json"
                    dump_ir_to_file(ir, ir_path)
                    saved_json.append(ir_path)
                    print(f"[SAVED] {ir_path}")
            else:
                # 입력 하나당 IR 1개에 모든 버전 결과 포함
                ir = build_ir(state)
                ir_path = jsondir / f"{base}_all_versions.json"
                dump_ir_to_file(ir, ir_path)
                saved_json.append(ir_path)
                print(f"[SAVED] {ir_path}")

        # 리포트 텍스트 추가 저장(선택)
        rpt = outdir / f"{base}_report.txt"
        try:
            from pprint import pformat
            rpt.write_text(pformat(state.get("report", {})), encoding="utf-8")
            print(f"[SAVED] {rpt}")
        except Exception as e:
            print(f"[WARN] 보고서 저장 실패: {e}")

    print("\n[DONE] 저장된 파일:")
    for f in saved_all:
        print(f"  - {f}")
    if args.emit_json:
        print("[DONE] 저장된 IR(JSON):")
        for f in saved_json:
            print(f"  - {f}")

if __name__ == "__main__":
    main()
