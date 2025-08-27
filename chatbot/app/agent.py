# agent.py
import os
import re
import math
from typing import List, Dict, Any, Optional, Tuple
from collections import Counter

from dotenv import load_dotenv
load_dotenv()  # .env 로드

# 선택 의존성
try:
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from langchain_community.vectorstores import FAISS
    from langchain.text_splitter import RecursiveCharacterTextSplitter
except Exception:
    ChatOpenAI = None
    OpenAIEmbeddings = None
    FAISS = None
    RecursiveCharacterTextSplitter = None

# PDF 텍스트 추출 (선택)
try:
    from pypdf import PdfReader  # pip install pypdf
except Exception:
    PdfReader = None

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# -------------------- 라우트 제안 규칙 --------------------
ROUTES = [
    {"label": "AI 변환기 소개", "url": "/support/transform/intro", "pat": r"(변환|transform).*(소개|intro)?"},
    {"label": "변환 하기", "url": "/support/transform/transformation", "pat": r"(변환(하기)?|transformation)"},
    {"label": "변환 이력 조회", "url": "/support/transform/view_transform", "pat": r"(변환.*(이력|기록)|view[_-]?transform)"},
    {"label": "테스트 이력 조회", "url": "/support/transform/view_test", "pat": r"(테스트.*(이력|기록)|view[_-]?test)"},
    {"label": "다운로드 (변환 산출물)", "url": "/support/transform/download", "pat": r"(다운로드|download)"},
    {"label": "AI 보안기 소개", "url": "/support/security/intro", "pat": r"(보안|security).*(소개|intro)"},
    {"label": "AI 보안 검사", "url": "/support/security/scan", "pat": r"(보안\s*(검사|스캔)|scan)"},
    {"label": "보안 취약점 탐지", "url": "/support/security/vulnerability", "pat": r"(취약점|vulnerability)"},
    {"label": "보안 점검결과", "url": "/support/security/report", "pat": r"(보안\s*(리포트|결과)|report)"},
    {"label": "전자정부프레임워크 가이드", "url": "/support/guide/egovframework", "pat": r"(전자정부|e[-_ ]?gov|egov).*가이드"},
    {"label": "자료실", "url": "/support/download", "pat": r"(자료실|자료|다운로드)"},
    {"label": "알림마당", "url": "/inform", "pat": r"(알림|inform)"},
]

def _suggest_actions_from_text(text: str, limit: int = 3) -> List[Dict[str, str]]:
    text_norm = (text or "").lower()
    hits = []
    for r in ROUTES:
        if re.search(r["pat"], text_norm, flags=re.I):
            hits.append({"label": r["label"], "url": r["url"]})
    if not hits:
        if ("보안" in text) or re.search(r"\bsecurity\b", text_norm):
            hits.append({"label": "AI 보안 검사", "url": "/support/security/scan"})
        if ("변환" in text) or re.search(r"\btransform|convert\b", text_norm):
            hits.append({"label": "변환 하기", "url": "/support/transform/transformation"})
        if ("가이드" in text) or ("전자정부" in text):
            hits.append({"label": "전자정부프레임워크 가이드", "url": "/support/guide/egovframework"})
    uniq, seen = [], set()
    for a in hits:
        if a["url"] in seen: 
            continue
        uniq.append(a); seen.add(a["url"])
        if len(uniq) >= limit: 
            break
    return uniq

# -------------------- RAG 인덱서 --------------------
class SimpleRAG:
    """
    기존 버전은 knowledge 디렉토리의 .txt/.md만 인덱싱했는데,
    여기에 .pdf 지원과 증분 ingest(업로드 즉시 반영)를 추가합니다.
    """
    def __init__(self, index_dir="./rag_index", knowledge_dir="./knowledge"):
        self.index_dir = index_dir
        self.knowledge_dir = knowledge_dir
        self.store = None
        self._ensure_loaded()

    # 내부 유틸: 문서 읽기
    def _read_txt_md(self, path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fp:
                return fp.read()
        except Exception:
            return ""

    def _read_pdf(self, path: str) -> str:
        if PdfReader is None:
            return ""
        try:
            reader = PdfReader(path)
            texts = []
            for pg in reader.pages:
                t = pg.extract_text() or ""
                if t:
                    texts.append(t)
            return "\n".join(texts)
        except Exception:
            return ""

    def _walk_knowledge(self) -> List[Tuple[str, str]]:
        """
        knowledge_dir 안의 .txt/.md/.pdf 를 읽어 [(source, text)] 반환
        """
        out: List[Tuple[str, str]] = []
        if not os.path.isdir(self.knowledge_dir):
            return out
        for root, _, files in os.walk(self.knowledge_dir):
            for f in files:
                low = f.lower()
                p = os.path.join(root, f)
                text = ""
                if low.endswith((".txt", ".md")):
                    text = self._read_txt_md(p)
                elif low.endswith(".pdf"):
                    text = self._read_pdf(p)
                if text.strip():
                    out.append((f, text))
        return out

    def _ensure_loaded(self):
        if not (FAISS and OpenAIEmbeddings):
            print("Warning: FAISS or OpenAIEmbeddings not available")
            return
        if not OPENAI_API_KEY:
            print("Warning: OPENAI_API_KEY not set, RAG will not work")
            return
        try:
            self.store = FAISS.load_local(
                self.index_dir,
                OpenAIEmbeddings(api_key=OPENAI_API_KEY),
                allow_dangerous_deserialization=True,
            )
            print(f"RAG store loaded successfully from {self.index_dir}")
        except Exception as e:
            print(f"Failed to load RAG store: {e}")
            print("Rebuilding from source...")
            self._rebuild_from_source()

    def _split(self, text: str):
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150) if RecursiveCharacterTextSplitter else None
        if splitter:
            return splitter.split_text(text)
        # 최악의 경우 간단 분할
        return [text[i:i+1000] for i in range(0, len(text), 1000)]

    def _rebuild_from_source(self):
        if not (FAISS and OpenAIEmbeddings):
            print("Error: FAISS or OpenAIEmbeddings not available")
            return
        if not OPENAI_API_KEY:
            print("Warning: OPENAI_API_KEY not set - creating dummy embeddings for testing")
            # API 키가 없을 때 더미 임베딩 생성 (테스트용)
            self._create_dummy_embeddings()
            return
        
        print("Rebuilding RAG index from knowledge files...")
        docs, meta = [], []
        knowledge_files = self._walk_knowledge()
        print(f"Found {len(knowledge_files)} knowledge files")
        
        for name, content in knowledge_files:
            print(f"Processing: {name}")
            chunks = self._split(content)
            for chunk in chunks:
                docs.append(chunk)
                meta.append({"source": name})
        
        if not docs:
            print("No documents found to index")
            return
        
        print(f"Creating embeddings for {len(docs)} chunks...")
        embeddings = OpenAIEmbeddings(api_key=OPENAI_API_KEY)
        self.store = FAISS.from_texts(docs, embeddings, metadatas=meta)
        os.makedirs(self.index_dir, exist_ok=True)
        self.store.save_local(self.index_dir)
        print(f"RAG index saved to {self.index_dir}")

    def _create_dummy_embeddings(self):
        """API 키가 없을 때 테스트용 더미 임베딩 생성"""
        print("Creating dummy embeddings for testing...")
        docs, meta = [], []
        knowledge_files = self._walk_knowledge()
        print(f"Found {len(knowledge_files)} knowledge files")
        
        for name, content in knowledge_files:
            print(f"Processing: {name}")
            chunks = self._split(content)
            for chunk in chunks:
                docs.append(chunk)
                meta.append({"source": name})
        
        if not docs:
            print("No documents found to index")
            return
        
        print(f"Creating dummy embeddings for {len(docs)} chunks...")
        
        # 더미 임베딩 생성 (랜덤 벡터)
        import numpy as np
        dimension = 1536  # OpenAI 임베딩 차원
        dummy_embeddings = np.random.rand(len(docs), dimension).astype('float32')
        
        # FAISS 인덱스 생성
        index = faiss.IndexFlatL2(dimension)
        index.add(dummy_embeddings)
        
        # 메타데이터와 함께 저장
        os.makedirs(self.index_dir, exist_ok=True)
        faiss.write_index(index, os.path.join(self.index_dir, "index.faiss"))
        
        # 메타데이터 저장
        import pickle
        docstore_data = {}
        for i, doc in enumerate(docs):
            docstore_data[i] = {
                "page_content": doc,
                "metadata": meta[i]
            }
        with open(os.path.join(self.index_dir, "index.pkl"), "wb") as f:
            pickle.dump({"docstore": docstore_data}, f)
        
        print(f"Dummy RAG index saved to {self.index_dir}")
        
        # 더미 store 객체 생성
        from langchain_community.vectorstores import FAISS
        self.store = FAISS.load_local(self.index_dir, None, allow_dangerous_deserialization=True)

    # 외부에서 호출: 전체 재색인
    def rebuild(self):
        self._rebuild_from_source()

    # 외부에서 호출: 파일 경로 리스트를 증분 인덱싱
    def ingest_files(self, paths: List[str]) -> int:
        if not (FAISS and OpenAIEmbeddings and OPENAI_API_KEY):
            return 0
        texts, metas = [], []
        for p in paths:
            low = p.lower()
            name = os.path.basename(p)
            if low.endswith((".txt", ".md")):
                t = self._read_txt_md(p)
            elif low.endswith(".pdf"):
                t = self._read_pdf(p)
            else:
                continue
            if not t.strip():
                continue
            for chunk in self._split(t):
                texts.append(chunk); metas.append({"source": name})
        if not texts:
            return 0
        if self.store is None:
            # 최초 빌드
            embeddings = OpenAIEmbeddings(api_key=OPENAI_API_KEY)
            self.store = FAISS.from_texts(texts, embeddings, metadatas=metas)
        else:
            self.store.add_texts(texts, metadatas=metas)
        os.makedirs(self.index_dir, exist_ok=True)
        self.store.save_local(self.index_dir)
        return len(texts)

    def list_files(self) -> List[str]:
        out = []
        if not os.path.isdir(self.knowledge_dir):
            return out
        for root, _, files in os.walk(self.knowledge_dir):
            for f in files:
                if f.lower().endswith((".txt", ".md", ".pdf")):
                    out.append(os.path.relpath(os.path.join(root, f), self.knowledge_dir))
        return sorted(out)

    def retrieve(self, query: str, k: int = 4) -> List[Dict[str, str]]:
        if not self.store:
            return []
        
        # 더미 임베딩인 경우 고도화된 키워드 매칭으로 검색
        if hasattr(self.store, 'docstore') and hasattr(self.store.docstore, '_dict'):
            return self._advanced_keyword_search(query, k)
        elif hasattr(self.store, 'docstore') and hasattr(self.store.docstore, 'metadata_dict'):
            # 다른 형태의 docstore 구조
            results = []
            query_lower = query.lower()
            
            for doc_id, metadata in self.store.docstore.metadata_dict.items():
                if 'page_content' in metadata:
                    content = metadata['page_content'].lower()
                    keywords = query_lower.split()
                    if any(keyword in content for keyword in keywords):
                        results.append({
                            "source": metadata.get('source', 'doc'),
                            "text": metadata['page_content']
                        })
                        if len(results) >= k:
                            break
            
            return results[:k]
        else:
            # 정상적인 FAISS 검색
            results = self.store.similarity_search(query, k=k)
            return [{"source": d.metadata.get("source", "doc"), "text": d.page_content} for d in results]

    def _advanced_keyword_search(self, query: str, k: int) -> List[Dict[str, str]]:
        """고도화된 키워드 기반 검색 (코사인 유사도 + TF-IDF + 키워드 매칭)"""
        import re
        import math
        from collections import Counter
        
        query_lower = query.lower()
        query_words = re.findall(r'\b\w+\b', query_lower)
        query_word_freq = Counter(query_words)
        
        # 점수 기반 검색 결과
        scored_results = []
        
        for doc_id, doc_info in self.store.docstore._dict.items():
            if hasattr(doc_info, 'page_content') and hasattr(doc_info, 'metadata'):
                content = doc_info.page_content.lower()
                source = doc_info.metadata.get('source', 'doc')
                
                # 1. 키워드 매칭 점수 (기본)
                keyword_score = self._calculate_keyword_score(query_words, content)
                
                # 2. TF-IDF 유사도 점수
                tfidf_score = self._calculate_tfidf_similarity(query_word_freq, content)
                
                # 3. 코사인 유사도 점수 (단어 벡터 기반)
                cosine_score = self._calculate_cosine_similarity(query_words, content)
                
                # 4. 파일명 매칭 보너스
                filename_bonus = self._calculate_filename_bonus(query_words, source)
                
                # 5. 문맥 관련성 점수
                context_score = self._calculate_context_relevance(query_lower, content)
                
                # 종합 점수 계산 (가중치 적용)
                total_score = (
                    keyword_score * 0.4 +  # 키워드 매칭 가중치 증가
                    tfidf_score * 0.2 +
                    cosine_score * 0.2 +
                    filename_bonus * 0.1 +
                    context_score * 0.1
                )
                
                if total_score > 0:
                    scored_results.append({
                        "source": source,
                        "text": doc_info.page_content,
                        "score": total_score,
                        "details": {
                            "keyword": keyword_score,
                            "tfidf": tfidf_score,
                            "cosine": cosine_score,
                            "filename": filename_bonus,
                            "context": context_score
                        }
                    })
        
        # 점수 순으로 정렬
        scored_results.sort(key=lambda x: x['score'], reverse=True)
        
        # 상위 k개 결과 반환
        results = []
        for result in scored_results[:k]:
            results.append({
                "source": result["source"],
                "text": result["text"]
            })
        
        return results

    def _calculate_keyword_score(self, query_words: list, content: str) -> float:
        """키워드 매칭 점수 계산"""
        score = 0
        content_words = content.split()
        content_lower = content.lower()
        
        for word in query_words:
            if len(word) < 2:
                continue
                
            # 정확한 매칭 (대소문자 무시)
            if word.lower() in content_lower:
                score += 3
                
            # 부분 매칭
            for content_word in content_words:
                if word.lower() in content_word.lower() or content_word.lower() in word.lower():
                    score += 1
                    
            # 연속된 단어 매칭 (구문 매칭)
            if len(word) > 3:
                if word.lower() in content_lower:
                    score += 2
        
        # 구문 매칭 보너스 (연속된 단어들)
        if len(query_words) > 1:
            for i in range(len(query_words) - 1):
                phrase = f"{query_words[i]} {query_words[i+1]}"
                if phrase.lower() in content_lower:
                    score += 5  # 구문 매칭에 높은 점수
        
        return score

    def _calculate_tfidf_similarity(self, query_freq: Counter, content: str) -> float:
        """TF-IDF 유사도 계산"""
        import re
        from collections import Counter
        
        # 문서에서 단어 빈도 계산
        content_words = re.findall(r'\b\w+\b', content.lower())
        content_freq = Counter(content_words)
        
        # 전체 문서 수 (임시로 고정값 사용)
        total_docs = 337
        
        similarity = 0
        for word, query_count in query_freq.items():
            if word in content_freq:
                # TF 계산
                tf = content_freq[word] / len(content_words)
                
                # IDF 계산 (간단한 버전)
                doc_freq = 1  # 임시값
                idf = math.log(total_docs / doc_freq) if doc_freq > 0 else 0
                
                # TF-IDF 점수
                tfidf = tf * idf
                similarity += tfidf * query_count
        
        return similarity

    def _calculate_cosine_similarity(self, query_words: list, content: str) -> float:
        """코사인 유사도 계산"""
        import re
        from collections import Counter
        
        # 쿼리와 문서의 단어 벡터 생성
        query_vector = Counter(query_words)
        content_words = re.findall(r'\b\w+\b', content.lower())
        content_vector = Counter(content_words)
        
        # 모든 고유 단어 수집
        all_words = set(query_vector.keys()) | set(content_vector.keys())
        
        if not all_words:
            return 0
        
        # 벡터 생성
        query_vec = [query_vector.get(word, 0) for word in all_words]
        content_vec = [content_vector.get(word, 0) for word in all_words]
        
        # 코사인 유사도 계산
        dot_product = sum(a * b for a, b in zip(query_vec, content_vec))
        query_magnitude = math.sqrt(sum(a * a for a in query_vec))
        content_magnitude = math.sqrt(sum(a * a for a in content_vec))
        
        if query_magnitude == 0 or content_magnitude == 0:
            return 0
        
        return dot_product / (query_magnitude * content_magnitude)

    def _calculate_filename_bonus(self, query_words: list, source: str) -> float:
        """파일명 매칭 보너스 점수"""
        source_lower = source.lower()
        bonus = 0
        
        for word in query_words:
            if len(word) > 2 and word in source_lower:
                bonus += 1
        
        return bonus

    def _calculate_context_relevance(self, query: str, content: str) -> float:
        """문맥 관련성 점수"""
        score = 0
        
        # 문장 단위로 관련성 검사
        sentences = content.split('.')
        
        for sentence in sentences:
            sentence_lower = sentence.lower()
            
            # 쿼리 단어들이 같은 문장에 함께 나타나는지 확인
            query_words = query.split()
            words_in_sentence = sum(1 for word in query_words if word in sentence_lower)
            
            if words_in_sentence >= 2:  # 2개 이상의 쿼리 단어가 같은 문장에 있으면
                score += 1
        
        return score

RAG = SimpleRAG(index_dir="./rag_index", knowledge_dir="./app/knowledge")

# -------------------- LLM --------------------
def _build_llm():
    if not OPENAI_API_KEY:
        return None, "no_api_key"
    if ChatOpenAI is None:
        return None, "missing_langchain_openai"
    try:
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3, api_key=OPENAI_API_KEY)
        return llm, "ok"
    except Exception as e:
        return None, f"init_error:{type(e).__name__}"

# -------------------- 메인 에이전트 --------------------
def call_agent(request: Dict[str, Any]) -> Dict[str, Any]:
    text = (request or {}).get("text", "")[:4000]
    actions = _suggest_actions_from_text(text)
    snippets = RAG.retrieve(text, k=4)

    llm, reason = _build_llm()
    if llm:
        context = "\n\n".join([f"[{i+1}] {s['text']}" for i, s in enumerate(snippets)])
        sys = ("당신은 eGovFrame 기반 사이트의 AI 도우미입니다. 한국어로 간결하고 실용적으로 답하세요. "
               "제공된 컨텍스트를 우선 활용하되, 모르면 솔직히 모른다고 하세요.")
        prompt = (
            f"사용자 질문: {text}\n\n"
            f"컨텍스트:\n{context if context else '(없음)'}\n\n"
            f"요청: 1~2문단으로 답하고, 사용자가 바로 이동할 수 있게 내부 기능을 1~3개 추천하세요."
        )
        messages = [{"role": "system", "content": sys}, {"role": "user", "content": prompt}]
        try:
            resp = llm.invoke(messages)
            reply = getattr(resp, "content", None) or (resp if isinstance(resp, "str") else "")
        except Exception as e:
            reply = "요청을 이해했어요. 관련 기능으로 이동할 수 있는 버튼을 아래에 제안드릴게요."
            reason = f"invoke_error:{type(e).__name__}"
    else:
        reply = ("요청을 이해했어요. OpenAI 키가 설정되면 더 자세히 답변할 수 있어요. "
                 "지금은 관련 기능 경로를 버튼으로 안내드릴게요.")

    citations = [{"source": s["source"], "snippet": s["text"][:180]} for s in snippets]
    return {
        "reply": reply.strip(),
        "actions": actions,
        "citations": citations,
        "meta": {"model": "gpt-4o-mini" if llm else "rule-fallback", "has_rag": bool(snippets), "reason": reason},
    }
