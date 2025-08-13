from __future__ import annotations
import argparse
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv
import glob

# scripts 폴더 안의 모듈 사용
from scripts import version_upgrade_agent as agent

DEFAULT_SEARCH_DIRS = [
    "examples/version/3.x",
]

def parse_args(root: Path) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Upgrade old eGovFrame Java to new version (e.g., 3.x -> 4.x)."
    )
    p.add_argument(
        "--input",
        help=r"자바 파일/디렉터리/글롭 패턴 (예: examples\version\3.x\*.java). 미지정 시 자동 스캔 또는 선택 모드.",
        default=None,
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="--input 없이 실행 시: 자동 스캔된 모든 파일을 일괄 변환(질문 없이).",
    )
    p.add_argument(
        "--output_dir",
        default=str(root / "converted_upgrade"),
        help="변환 결과 저장 디렉터리(기본: converted_upgrade).",
    )
    p.add_argument(
        "--target",
        default="4.3",
        help="목표 버전 문자열(기본: 4.3). 파일명 접미사에 사용됩니다.",
    )
    p.add_argument(
        "--emit_json",
        action="store_true",
        help="업그레이드 결과와 함께 IR(JSON)도 저장합니다.",
    )
    p.add_argument(
        "--json_dir",
        default=str(root / "converted_upgrade_ir"),
        help="IR(JSON) 저장 디렉터리(기본: converted_upgrade_ir).",
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
    seen, uniq = set(), []
    for f in files:
        if f not in seen:
            uniq.append(f)
            seen.add(f)
    return uniq

def _choose(files: List[Path]) -> List[Path]:
    print("\n[SELECT] 업그레이드할 파일을 선택하세요:")
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
    if user_input:
        # 글롭 패턴이면 glob 사용
        if any(ch in user_input for ch in ["*", "?", "[", "]"]):
            pattern = str(_to_abs(root, Path(user_input)))
            files = [Path(p) for p in glob.glob(pattern) if Path(p).lower().endswith(".java")]
            if not files:
                raise FileNotFoundError(f"글롭과 일치하는 파일이 없습니다: {user_input}")
            return files

        p = _to_abs(root, Path(user_input))
        if p.is_file():
            if p.suffix.lower() != ".java":
                raise ValueError(f"자바 파일이 아닙니다: {p}")
            return [p]
        if p.is_dir():
            files = sorted(p.rglob("*.java"))
            if not files:
                raise FileNotFoundError(f"디렉터리 내에 .java 파일이 없습니다: {p}")
            return files
        raise FileNotFoundError(p)

    candidates = _scan_candidates(root)
    if not candidates:
        raise FileNotFoundError(
            "자동 스캔에서 .java 파일을 찾지 못했습니다.\n"
            f"검색 경로: {', '.join(DEFAULT_SEARCH_DIRS)}\n"
            "예) --input examples\\version\\3.x  또는  --input \"examples\\version\\3.x\\*.java\""
        )
    if use_all:
        return candidates
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

    print(f"[INFO] Target version : {args.target}")
    print(f"[INFO] Output dir     : {outdir}")
    print(f"[INFO] Input files    : {len(files)}개")

    saved_java: List[Path] = []
    saved_json: List[Path] = []

    for fp in files:
        code = fp.read_text(encoding="utf-8")

        state: agent.UpgradeState = {
            "input_code": code,
            "target_version": args.target,
            "retrieved": [],
            "result": "",
            "report": {},
        }

        state = agent.retrieve_examples(state)
        state = agent.convert_code(state)
        state = agent.finalize(state)

        result = state.get("result", "").strip()
        if not result:
            print(f"[WARN] 결과 없음: {fp}")
            continue

        out_file = outdir / f"{fp.stem}_{args.target}.java"
        out_file.write_text(result, encoding="utf-8")
        saved_java.append(out_file)
        print(f"[SAVED] {out_file}")

        if args.emit_json:
            ir = agent.build_ir(state)
            ir_path = jsondir / f"{fp.stem}_{args.target}.json"
            agent.dump_ir_to_file(ir, ir_path)
            saved_json.append(ir_path)
            print(f"[SAVED] {ir_path}")

    print("\n[DONE] 저장된 파일:")
    for f in saved_java:
        print(f"  - {f}")
    if args.emit_json:
        print("[DONE] 저장된 IR(JSON):")
        for f in saved_json:
            print(f"  - {f}")

if __name__ == "__main__":
    main()
