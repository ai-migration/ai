import requests
import json
from bs4 import BeautifulSoup
import urllib.parse
from openai import OpenAI
import faiss
import numpy as np
import pandas as pd
from tqdm import tqdm
import tiktoken
from langchain.vectorstores import FAISS
from langchain.embeddings import OpenAIEmbeddings
from langchain.docstore.document import Document
import os
import re

OWNER = "eGovFramework"
REPO = "egovframe-common-components"
BRANCH = "main"
TARGET_DIR = "src/main/java"
BASE_URL = "https://www.egovframe.go.kr"
INIT_GUIDE_URL = f"{BASE_URL}/wiki/doku.php?id=egovframework:com:v4.3:init_guide"
# 최대 토큰 수
MAX_TOKENS = 8192
EMBED_MODEL = "text-embedding-3-small"

# 도메인(상위폴더), 기능(중간), 계층(Controller/DAO 등) 분리
def classify_path_info(path):
    '''
    src/main/java/egovframework/com/sym/mnu/mcm/service/MenuCreatVO.java -> service 경로에 있지만 VO로 분리
    src/main/java/egovframework/com/cop/bbs/web/EgovBBSController.java
    src/main/java/egovframework/com/sym/log/wlg/web/EgovWebLogInterceptor.java -> controller가 없지만 web에 있으니까 controller로 분리
    src/main/java/egovframework/com/sym/log/wlg/service/impl/EgovWebLogServiceImpl.java
    '''
    segments = path.split('/')
    domain = segments[5] if len(segments) > 5 else "unknown"  # cop, sym, uss 등
    feature = segments[6] if len(segments) > 6 and not segments[6].endswith(".java") else "common"
    filename = os.path.basename(path)

    dir, filename = os.path.split(path)

    if 'controller' in filename.lower() or 'web' in dir.lower():
        component = 'Controller'
    elif 'serviceimple' in filename.lower() or 'impl' in dir.lower():
        component = 'ServiceImpl'
    elif 'vo' in filename.lower():
        component = 'VO'
    elif 'mapper' in dir.lower():
        component = 'Mapper'
    elif 'handler' in dir.lower() or 'hndlr' in dir.lower() or 'handler' in filename.lower():
        component = 'Handler'
    elif 'service' in filename.lower() or ('service' in dir.lower() and ('vo' not in filename.lower() or 'serviceimple' in filename.lower())):
        component = 'Service'
    else:
        component = 'Other'
    return domain, feature, component

# GitHub API로 전체 트리 가져오기
def fetch_file_list():
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/git/trees/{BRANCH}?recursive=1"
    res = requests.get(url)
    res.raise_for_status()
    data = res.json()
    files = data["tree"]
    java_files = [f for f in files if f["path"].startswith(TARGET_DIR) and f["path"].endswith(".java")]
    return java_files

# 코드 수집 및 저장
def collect_egov_code(descriptions, save_path):
    java_files = fetch_file_list()
    raw_base = f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}"

    with open(save_path, "w", encoding="utf-8") as out_f:
        for f in java_files:
            rel_path = f["path"]

            filename = rel_path.split("/")[-1]
            raw_url = f"{raw_base}/{rel_path}"
            domain, feature, component = classify_path_info(rel_path)

            if component not in ('Controller', 'Service', 'ServiceImpl', 'DAO', 'VO'):
              continue
 
            try:
                code = requests.get(raw_url).text.strip()

                entry = {
                    "description": descriptions.get(filename, ''),
                    "title": filename.replace(".java", ""),
                    "path": rel_path,
                    "domain": domain,      # 예: cop
                    "feature": feature,    # 예: bbs
                    "type": component,     # 예: Controllers
                    "code": code
                }
                out_f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception as e:
                print(f"⚠️ Error loading {raw_url}: {e}")

# 공통 컴포넌트 가이드 페이지에서 모든 페이지 수집
def get_subpage_links(url: str) -> list:
    res = requests.get(url)
    res.encoding = "utf-8"
    soup = BeautifulSoup(res.text, 'html.parser')

    links = []
    for ul in soup.find_all("ul"):
        for a in ul.find_all("a", href=True):
            href = a["href"]
            if href.startswith('/wiki/doku.php?id=egovframework:')  and 'init_guide' not in href:
            # if (href.startswith("/wiki/doku.php?id=egovframework:com:v4.3:") or href.startswith("/wiki/doku.php?id=egovframework:com:v3")) and 'init_guide' not in href:
                page_url = urllib.parse.urljoin(BASE_URL, href)
                page_name = a.get_text(strip=True)
                print(f"🔍 링크 수집 중: {page_name} ({page_url})")
                links.append({"url": page_url, "title": page_name})
    return links

# 콩통 컴포넌트 코드 파일에 대한 설명
def get_code_description(pages) -> dict:
    """
    각 하위 페이지에서 유형/대상소스명/비고 표 추출
    """
    descriptions = {}
    for page in pages:
        print(f"🔍 설명 수집 중: {page['title']} ")
        response = requests.get(page['url'])
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        tables = soup.find_all("table")

        for table in tables:
            headers = [th.get_text(strip=True) for th in table.find_all("th")]
            if not ({"유형", "비고", "대상소스명"}.issubset(set(headers)) or 
                    {"유형", "비고", "대상소스"}.issubset(set(headers)) or
                    {"유형", "소스", "설명"}.issubset(set(headers)) or
                    {"유형", "대상소스명", "설명", "비고"}.issubset(set(headers))):
                continue

            for row in table.find_all("tr")[1:]:
                cells = row.find_all("td")

                if len(cells) < 3:
                    continue

                if cells[1].get_text(strip=True).endswith('.java'):
                    filename = re.split(r'[./]', cells[1].get_text(strip=True))[-2] + '.java'

                    # 설명 추출
                    if len(headers) == 4:
                        parts = [cells[2].get_text(strip=True), cells[3].get_text(strip=True)]
                    elif len(headers) == 3:
                        parts = [cells[2].get_text(strip=True)]
                    else:
                        parts = []

                    # 빈 문자열 제거 후 조인
                    desc = ', '.join([p for p in parts if p])

                    if filename in descriptions:
                        descriptions[filename] += f", {desc}"
                    else:
                        descriptions[filename] = desc

            break   
    
    # 중복 설명 제거
    for k, v in descriptions.items():
        res = ', '.join(dict.fromkeys(item.strip() for item in v.split(',')))
        descriptions[k] = res
    return descriptions

def build_vectordb(jsonpath, dbpath, embedding_model):
    docs = []

    with open(jsonpath, 'r', encoding='utf-8') as f:
        for line in f:
            data = json.loads(line)
            # if not data['코드']:
            #     continue

            doc = Document(
                page_content = f"[description] {data['description']}\n[role]{data['type']}\n[code]{data['code']}",
                metadata = {
                    "title": data["title"],
                    "path": data["path"],
                    "type": data["type"],
                    "domain": data["domain"],
                    "feature": data.get("feature", "unknown"),
                    "description": data["description"]
                }
            )
            docs.append(doc)
    
    first_doc = docs[0]
    vectorstore = FAISS.from_documents([first_doc], embedding_model)

    # 나머지 문서들 하나씩 추가
    for doc in tqdm(docs[1:], desc="Embedding docs"):
        partial = FAISS.from_documents([doc], embedding_model)
        vectorstore.merge_from(partial)

    # 저장
    vectorstore.save_local(dbpath)

    # splitter = RecursiveCharacterTextSplitter(
    #     chunk_size=1000, chunk_overlap=100
    # )
    # split_docs = splitter.split_documents(docs)  # 여러 개로 분할된 Document 리스트
    
    # vectorstore = FAISS.from_documents(split_docs, embedding_model)
    # vectorstore.save_local(dbpath)

    # vectorstore = FAISS.from_documents(docs, embedding_model)
    # vectorstore.save_local(dbpath)
    print(f"✅ FAISS DB 저장 완료: {dbpath}/index.faiss")

if __name__ == "__main__":
    subpages = get_subpage_links(INIT_GUIDE_URL)
    descriptions = get_code_description(subpages)
    # with open("descriptions_0803.json", "w", encoding='utf-8') as json_file:
    #     json.dump(descriptions, json_file, ensure_ascii=False, indent=2)
    # collect_egov_code(descriptions, 'egovcode_0805.jsonl')

    embedding_model = OpenAIEmbeddings(model="text-embedding-3-small", api_key='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')
    build_vectordb('egovcode_0805.jsonl', 'eGovCodeDB_0805', embedding_model)
    
    # get_code_description([{'url': 'https://www.egovframe.go.kr/wiki/doku.php?id=egovframework:ldap%EC%A1%B0%EC%A7%81%EB%8F%84%EA%B4%80%EB%A6%AC', 
    #                        'title': 'LDAP조직도관리(v3.2 신규)'}])
    # print(classify_path_info("src/main/java/egovframework/com/cmm/AltibaseClobStringTypeHandler.java"))