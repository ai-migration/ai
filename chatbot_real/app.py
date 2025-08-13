# app.py — eGovFrame 톤, 한 화면(업로드+인덱싱+챗봇)
# - 답변 가독성 향상(기호/숫자 기준 줄바꿈)
# - "n페이지 요약" 시 해당 페이지 이미지 시각화(채팅 말풍선 내부)
import os
import re
import time
import base64
import html as pyhtml
import streamlit as st
import pdfplumber
import fitz  # PyMuPDF

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.document_loaders import PDFPlumberLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.chains import RetrievalQA

# ================== 설정 ==================
APP_TITLE = "eGovFrame 챗봇"
PERSIST_DIR = "egov_chroma_db"
UPLOADED_PDF_PATH = "uploaded_egov.pdf"
EMBEDDING_MODEL = "text-embedding-3-small"
CHAT_MODEL = "gpt-4o-mini"
TOP_K = 3

# OpenAI Key (.streamlit/secrets.toml)
if "OPENAI_API_KEY" in st.secrets:
    os.environ["OPENAI_API_KEY"] = st.secrets["OPENAI_API_KEY"]

st.set_page_config(page_title=APP_TITLE, layout="wide")

# ================== 스타일 ==================
st.markdown("""
<style>
:root{
  --egov-primary:#0B5ED7; --egov-border:#e5e7eb; --egov-muted:#6b7280;
}
.block-container{padding-top:0.8rem;}
.egov-topbar{background:var(--egov-primary); color:#fff; padding:14px 16px; border-radius:10px; margin-bottom:10px;}
.egov-title{font-size:18px; font-weight:700;}
.egov-sub{font-size:12px; opacity:.9;}
.egov-card{background:#fff; border:1px solid var(--egov-border); border-radius:12px; padding:14px;}
.egov-label{font-weight:600; font-size:14px;}
.egov-required::after{content:" *"; color:#dc2626;}

#chat-box{
  height:62vh; overflow-y:auto; border:1px solid var(--egov-border);
  border-radius:12px; padding:10px; background:#fff;
}
.bubble{max-width:92%; padding:10px 12px; border-radius:12px; margin:6px 0; display:inline-block; line-height:1.5; word-break:break-word;}
.user{background:#eef2ff; color:#1e3a8a; margin-left:auto;}
.bot{background:#f3f4f6; color:#111827; margin-right:auto;}
.row{display:flex; width:100%;}
.meta{font-size:11px; color:var(--egov-muted); margin-top:6px;}
.chat-input-row{display:flex; gap:8px; margin-top:8px;}
.chat-input-row > div{flex:1;}
img.chat-page{max-width:100%; border-radius:8px; border:1px solid #eee; margin-top:8px;}
</style>
""", unsafe_allow_html=True)

# ================== 세션 ==================
default_state = {
    "vectordb": None,
    "history": [],  # list of dicts OR tuples (for 호환): {"role":"user"/"assistant","text":..., "image_b64":..., "image_page":...}
    "pdf_meta": {"name": None, "pages": 0},
}
for k, v in default_state.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ================== 유틸 ==================
def load_vectordb_if_exists():
    if os.path.isdir(PERSIST_DIR):
        try:
            emb = OpenAIEmbeddings(model=EMBEDDING_MODEL)
            st.session_state.vectordb = Chroma(persist_directory=PERSIST_DIR, embedding_function=emb)
            return True
        except Exception:
            return False
    return False

def build_index_from_pdf(pdf_path: str):
    loader = PDFPlumberLoader(pdf_path)
    docs = loader.load()
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=120)
    chunks = splitter.split_documents(docs)
    emb = OpenAIEmbeddings(model=EMBEDDING_MODEL)
    vectordb = Chroma.from_documents(chunks, embedding=emb, persist_directory=PERSIST_DIR)
    vectordb.persist()
    st.session_state.vectordb = vectordb

def extract_page_count(pdf_path: str) -> int:
    try:
        with pdfplumber.open(pdf_path) as pdf:
            return len(pdf.pages)
    except Exception:
        return 0

def extract_page_text(pdf_path: str, page_number: int) -> str:
    """1-based page number; pdfplumber로 직접 추출"""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if 1 <= page_number <= len(pdf.pages):
                return pdf.pages[page_number-1].extract_text() or ""
    except Exception:
        pass
    return ""

def render_page_image_b64(pdf_path: str, page_no: int, zoom: float = 1.6) -> str | None:
    """해당 페이지를 PNG로 렌더링해 base64 문자열을 반환"""
    try:
        doc = fitz.open(pdf_path)
        if 1 <= page_no <= len(doc):
            page = doc.load_page(page_no - 1)
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            b = pix.tobytes("png")
            return base64.b64encode(b).decode("utf-8")
    except Exception:
        return None
    return None

def summarize_page(page_no: int) -> tuple[str, str | None]:
    """
    요약 텍스트와 (가능하면) 해당 페이지 이미지 base64를 함께 반환.
    1) pdfplumber로 텍스트 추출
    2) 실패 시, Chroma 인덱스에서 해당 페이지 문서 모아 요약
    """
    # 1) 직접 추출
    text = extract_page_text(UPLOADED_PDF_PATH, page_no)

    # 2) 폴백: 인덱스에서 특정 페이지 문서 모으기
    if (not text.strip()) and (st.session_state.vectordb is not None):
        try:
            col = getattr(st.session_state.vectordb, "_collection", None)
            if col is not None and hasattr(col, "get"):
                merged = ""
                for key in (page_no-1, page_no, str(page_no-1), str(page_no)):
                    out = col.get(where={"page": key})
                    if out and out.get("documents"):
                        merged += "\n".join(out["documents"]) + "\n"
                if merged.strip():
                    text = merged
        except Exception:
            pass

    if not text.strip():
        return "해당 페이지에서 텍스트를 찾지 못했습니다. (스캔본일 수 있어요)", None

    prompt = (
        "아래는 전자정부 표준 문서의 일부입니다.\n"
        "과장 없이 핵심만 5~8줄로 한국어 요약하세요. 항목은 '-'로 시작해 주세요.\n\n"
        f"---\n{text}\n---"
    )
    llm = ChatOpenAI(model=CHAT_MODEL, temperature=0.2, max_tokens=900)
    out = llm.invoke(prompt)
    answer = out.content if hasattr(out, "content") else str(out)

    img_b64 = render_page_image_b64(UPLOADED_PDF_PATH, page_no)
    return answer, img_b64

def rag_answer(query: str, k: int = TOP_K):
    llm = ChatOpenAI(model=CHAT_MODEL, temperature=0.2)
    if st.session_state.vectordb is None:
        resp = llm.invoke("다음 질문에 한국어로 간결하게 답해줘.\n질문: " + query)
        return (resp.content if hasattr(resp, "content") else str(resp)), []
    retriever = st.session_state.vectordb.as_retriever(search_kwargs={"k": int(k)})
    qa = RetrievalQA.from_chain_type(llm=llm, chain_type="stuff", retriever=retriever, return_source_documents=True)
    result = qa.invoke({"query": query})
    return result.get("result", ""), result.get("source_documents", [])

def format_answer_html(text: str, is_assistant: bool = True) -> str:
    """
    답변 가독성 향상을 위해:
    - HTML 이스케이프 → 안전 출력
    - 줄바꿈(\n) 유지
    - ' - ', ' • ', ' · ' 같은 구분자 앞에 줄바꿈 삽입
    - 숫자목록 ' 1. ', ' 2) ' 패턴에도 줄바꿈 삽입
    """
    if text is None:
        return ""
    s = pyhtml.escape(text)

    # 기본 줄바꿈
    s = s.replace("\r\n", "\n").replace("\r", "\n")

    # bullet 기호 앞에 줄바꿈 삽입
    s = s.replace(" • ", "<br> • ").replace(" · ", "<br> · ").replace(" - ", "<br> - ")

    # 숫자 목록(1. / 1) / 1 ) / ① 등 간단 패턴)
    s = re.sub(r'(?<!^)\s(?=\d{1,2}[.)]\s)', '<br>', s)
    s = re.sub(r'(?<!^)\s(?=[①-⑳])', '<br>', s)

    # 최종 개행 처리
    s = s.replace("\n", "<br>")
    return s

# 최초 진입 시 기존 인덱스 자동 로드
if st.session_state.vectordb is None:
    load_vectordb_if_exists()

# ================== 상단바 ==================
st.markdown(f"""
<div class="egov-topbar">
  <div class="egov-title">{APP_TITLE}</div>
  <div class="egov-sub">문서 업로드 → 적용 후, 오른쪽 챗봇에서 질문하세요.</div>
</div>
""", unsafe_allow_html=True)

# ================== 레이아웃 ==================
left, right = st.columns([1, 2], gap="large")

# ---- 좌: 업로드/인덱싱 ----
with left:
    st.markdown('<div class="egov-card">', unsafe_allow_html=True)
    st.markdown('<div class="egov-label egov-required">문서 업로드(PDF)</div>', unsafe_allow_html=True)
    file = st.file_uploader("전자정부 표준프레임워크 관련 PDF를 선택하세요.", type=["pdf"], label_visibility="collapsed")
    st.caption("업로드 후 ‘적용’ 버튼을 누르면 챗봇이 문서를 근거로 답합니다.")

    c1, c2 = st.columns(2)
    apply_click = c1.button("적용", type="primary", use_container_width=True)
    reset_click = c2.button("초기화", use_container_width=True)

    if reset_click:
        try:
            if os.path.exists(UPLOADED_PDF_PATH):
                os.remove(UPLOADED_PDF_PATH)
        except Exception:
            pass
        try:
            import shutil
            if os.path.isdir(PERSIST_DIR):
                shutil.rmtree(PERSIST_DIR)
        except Exception:
            pass
        st.session_state.vectordb = None
        st.session_state.history = []
        st.session_state.pdf_meta = {"name": None, "pages": 0}
        st.toast("초기화 완료", icon="✅")

    if apply_click:
        if file is None:
            st.warning("업로드할 PDF를 선택하세요.")
        else:
            with st.spinner("업로드 중..."):
                with open(UPLOADED_PDF_PATH, "wb") as f:
                    f.write(file.getbuffer())
                st.session_state.pdf_meta["name"] = file.name
                st.session_state.pdf_meta["pages"] = extract_page_count(UPLOADED_PDF_PATH)
                build_index_from_pdf(UPLOADED_PDF_PATH)
            st.success("적용 완료! 이제 오른쪽 챗봇에 질문해보세요.")
    st.markdown('</div>', unsafe_allow_html=True)

# ---- 우: 챗봇(스크롤 박스 + 입력) ----
with right:
    st.markdown('<div class="egov-card">', unsafe_allow_html=True)
    st.markdown("#### 챗봇 대화", unsafe_allow_html=True)

    # 채팅 박스(스크롤)
    chat_html = ['<div id="chat-box">']
    if not st.session_state.history:
        chat_html.append('<div class="row"><div class="bubble bot">안녕하세요! 어떻게 도와드릴까요?</div></div>')
    else:
        for item in st.session_state.history[-200:]:
            # 과거 튜플 호환 처리
            if isinstance(item, tuple):
                role, content = item
                text = content
                image_b64 = None
                image_page = None
            else:
                role = item.get("role", "assistant")
                text = item.get("text", "")
                image_b64 = item.get("image_b64")
                image_page = item.get("image_page")

            klass = "user" if role == "user" else "bot"
            if role == "assistant":
                text_html = format_answer_html(text, True)
            else:
                text_html = pyhtml.escape(text).replace("\n", "<br>")

            bubble = f'<div class="row"><div class="bubble {klass}">{text_html}'
            if image_b64:
                bubble += f'<img class="chat-page" src="data:image/png;base64,{image_b64}" />'
                if image_page:
                    bubble += f'<div class="meta">페이지 {image_page} 미리보기</div>'
            bubble += '</div></div>'
            chat_html.append(bubble)
    chat_html.append("</div>")
    st.markdown("\n".join(chat_html), unsafe_allow_html=True)

    # 입력창을 만들기 전에 clear 플래그 확인(위젯 생성 전 초기화)
    if st.session_state.get("clear_input"):
        st.session_state["user_input"] = ""
        del st.session_state["clear_input"]

    # 입력창 + 전송 버튼 (한 줄)
    c = st.container()
    with c:
        left_in, right_btn = st.columns([6, 1])
        user_text = left_in.text_input(
            "질문을 입력하세요. (예: 9페이지 요약해줘)",
            key="user_input",
            label_visibility="collapsed",
        )
        send = right_btn.button("전송", use_container_width=True)

    # 전송 처리
    if send and user_text.strip():
        q = user_text.strip()
        st.session_state.history.append({"role": "user", "text": q})

        # "n페이지 요약" 우선 처리
        page_pat = re.search(r'(\d+)\s*(?:페이지|쪽|page|p)\b', q, flags=re.I)
        wants_summary = ("요약" in q) and (page_pat is not None)

        if wants_summary and os.path.exists(UPLOADED_PDF_PATH):
            page_no = int(page_pat.group(1))
            maxp = st.session_state.pdf_meta.get("pages") or 0
            if maxp and (page_no < 1 or page_no > maxp):
                answer = f"{page_no}페이지는 범위를 벗어났습니다. 1~{maxp} 사이로 요청해주세요."
                st.session_state.history.append({"role": "assistant", "text": answer})
            else:
                with st.spinner(f"{page_no}페이지 요약 중..."):
                    answer, img_b64 = summarize_page(page_no)
                st.session_state.history.append({
                    "role": "assistant",
                    "text": answer,
                    "image_b64": img_b64,
                    "image_page": page_no
                })
        else:
            # 일반 RAG 질의
            with st.spinner("생각 중..."):
                answer, _ = rag_answer(q, k=TOP_K)
            st.session_state.history.append({"role": "assistant", "text": answer})

        # 입력창은 직접 비우지 말고, 플래그만 세운 후 rerun
        st.session_state["clear_input"] = True
        st.rerun()

    # 채팅 박스 하단 스크롤
    st.markdown("""
        <script>
        const box = window.parent.document.querySelector('#chat-box');
        if (box) { box.scrollTop = box.scrollHeight; }
        </script>
    """, unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)






                    
                    















