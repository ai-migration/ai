from langchain_community.vectorstores import FAISS
from langchain_community.document_loaders import TextLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from dotenv import load_dotenv
import os
import glob

#벡터 DB 저장

# ✅ .env 파일에서 환경변수 로드
load_dotenv()

# ✅ 임베딩 객체 생성
embedding = OpenAIEmbeddings(model="text-embedding-3-large")

# ✅ 파일 경로 설정 (예: examples/version/3.6.0 안의 자바 파일들)
version_dirs = ["examples/version/2.7.1", "examples/version/3.2.0", "examples/version/3.5.1", "examples/version/3.6.0", "examples/version/3.7.0", "examples/version/3.9.0"]

docs = []
for version in version_dirs:
    for filepath in glob.glob(f"{version}/*.java"):
        loader = TextLoader(filepath, encoding="utf-8")
        docs.extend(loader.load())

# ✅ 텍스트 분할
text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
splits = text_splitter.split_documents(docs)

# ✅ FAISS 벡터 DB로 저장
db = FAISS.from_documents(splits, embedding)
db.save_local("vector_store/version_vector_store")
print("✅ 버전별 자바 코드 벡터 DB 저장 완료!")



