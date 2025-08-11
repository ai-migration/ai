import os
import re
import streamlit as st

# ── 몽키패치: langchain_community 구버전 ChatCompletion.create → v1 API 매핑 ──
import openai as _openai_module
from openai import OpenAI as OpenAIClient

def _legacy_chat_completion_create(
    *, model=None, model_name=None, openai_api_key=None, **kwargs
):
    actual_model = model or model_name
    key = openai_api_key or st.secrets["OPENAI_API_KEY"]
    client = OpenAIClient(api_key=key)
    return client.chat.completions.create(model=actual_model, **kwargs)

_openai_module.ChatCompletion = type(
    "ChatCompletion", (), {"create": staticmethod(_legacy_chat_completion_create)}
)

# ── 나머지 import ──
from openai import OpenAI as OpenAIClientRaw
from langchain_community.document_loaders import PDFPlumberLoader
from langchain_community.embeddings.openai import OpenAIEmbeddings
from langchain_community.vectorstores.chroma import Chroma
from langchain_community.llms.openai import OpenAI as CC_OpenAI
from langchain.chains import RetrievalQA
from langchain.text_splitter import RecursiveCharacterTextSplitter
import fitz

# Streamlit 레이아웃
st.set_page_config(layout="wide", page_title="전자정부 프레임워크 챗봇")
col1, col2 = st.columns([2, 1])

# ▶ 오른쪽: PDF 업로드 & 인덱스 1회 생성
with col2:
    st.header("PDF 업로드 및 뷰어")
    uploaded = st.file_uploader("PDF 업로드", type="pdf")
    if uploaded and "vectordb" not in st.session_state:
        st.info("PDF 인덱싱 중…")
        path = "uploaded_egov.pdf"
        with open(path, "wb") as f:
            f.write(uploaded.getbuffer())
        st.session_state["uploaded_path"] = path

        loader = PDFPlumberLoader(path)
        docs = loader.load()
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        chunks = splitter.split_documents(docs)

        embeddings = OpenAIEmbeddings()
        vectordb = Chroma.from_documents(chunks, embeddings, persist_directory="egov_chroma_db")
        st.session_state.vectordb = vectordb

        pdf_doc = fitz.open(stream=uploaded.getbuffer(), filetype="pdf")
        st.session_state.page_images = [
            page.get_pixmap(dpi=150).tobytes("png") for page in pdf_doc
        ]
        st.success("업로드 완료! 🎉")

    if "page_images" in st.session_state:
        st.subheader("PDF 미리보기")
        for i, img in enumerate(st.session_state.page_images[:5], 1):
            st.image(img, caption=f"Page {i}", width=100)

# ▶ 왼쪽: 챗봇 UI
with col1:
    st.title("전자정부 프레임워크 챗봇")
    if "openai_model" not in st.session_state:
        st.session_state["openai_model"] = "gpt-3.5-turbo"

    # 시스템 메시지 초기화
    if "initialized" not in st.session_state:
        st.session_state.messages = [{
            "role": "system",
            "content": (
                "전자정부 표준프레임워크 관련 질문은 문서를 기반으로 답변하고, "
                "그 외 일반 대화(인사, 잡담 등)는 자연스럽게 한국어로 응답하세요."
            )
        }]
        st.session_state.initialized = True

    # 클라이언트 준비
    raw_client = OpenAIClientRaw(api_key=st.secrets["OPENAI_API_KEY"])
    chain_llm  = CC_OpenAI(
        model_name=st.session_state.get("openai_model", "gpt-3.5-turbo"),
        openai_api_key=st.secrets["OPENAI_API_KEY"],
        temperature=0
    )

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("질문을 입력하세요"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        reply = None
        docs_and_scores = []

        # 1) 인사 처리
        if prompt.strip().lower() in {"안녕","안녕하세요","hi","hello"}:
            resp = raw_client.chat.completions.create(
                model=st.session_state["openai_model"],
                messages=st.session_state.messages
            )
            reply = resp.choices[0].message.content

        # 2) 페이지 요약 처리
        else:
            m = re.match(r"(\d+)\s*페이지 요약", prompt)
            if m and "uploaded_path" in st.session_state:
                target = int(m.group(1)) - 1
                loader = PDFPlumberLoader(st.session_state["uploaded_path"])
                all_docs = loader.load()
                page_texts = [
                    d.page_content
                    for d in all_docs
                    if d.metadata.get("page",1)-1 == target
                ]
                to_sum = "\n".join(page_texts)
                resp = raw_client.chat.completions.create(
                    model=st.session_state["openai_model"],
                    messages=[
                        {"role":"system","content":"다음 텍스트를 한국어로 간결히 요약해 주세요."},
                        {"role":"user","content":to_sum}
                    ]
                )
                reply = resp.choices[0].message.content
                docs_and_scores = [{"metadata":{"page":target+1}}]

        # 3) 일반 RAG vs GPT
        if reply is None and "vectordb" in st.session_state:
            retriever = st.session_state.vectordb.as_retriever(search_kwargs={"k":3})
            docs_and_scores = retriever.get_relevant_documents(prompt)
            if docs_and_scores:
                qa = RetrievalQA.from_chain_type(
                    llm=chain_llm, chain_type="stuff", retriever=retriever
                )
                reply = qa.run(prompt)

                # RAG이 “모르겠다”류면 GPT로 재시도
                if any(kw in reply.lower() for kw in ["i'm sorry","don't know","정보가 없습니다"]):
                    reply = None
                    docs_and_scores = []

        # 4) 최종 GPT fallback
        if reply is None:
            resp = raw_client.chat.completions.create(
                model=st.session_state["openai_model"],
                messages=st.session_state.messages
            )
            reply = resp.choices[0].message.content

        st.session_state.messages.append({"role":"assistant","content":reply})
        with st.chat_message("assistant"):
            st.markdown(reply)

        # 5) RAG 모드일 때만 페이지 이미지
        if docs_and_scores:
            pages = sorted({
                (d["metadata"]["page"]-1) if isinstance(d, dict) else d.metadata.get("page",1)-1
                for d in docs_and_scores
            })
            for pg in pages:
                with st.expander(f"관련 페이지: {pg+1}"):
                    st.image(st.session_state.page_images[pg], use_container_width=True)
                    
                    















