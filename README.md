# AI

> Python/Java 기반의 코드를 **전자정부표준프레임워크(eGovFramework)** 스타일로 변환하고,  
> **보안/품질 분석까지 자동화**하는 **멀티 에이전트** 시스템

---

## ✨ 주요 기능
- **Orchestrate**: API를 통해 각 에이전트를 실행하고 응답
- **Translate**: Python/Java → eGov(Controller/Service/VO 등) 변환 및 생성을 수행하고  리포트를 생성하는 에이전트
- **Upgrade/Downgrade**: eGov 버전 컨트롤 에이전트
- **Security**: 보안 취약점 분석과 보안 가이드를 생성하는 에이전트
- **Chatbot**: 서비스 이용 도우미 역할의 챗봇 에이전트

---
## ⚙️ 기술 스택
| 영역 | 기술 |
|------|------|
| Language | <img src="https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=Python&logoColor=white"/> |
| Agent | <img src="https://img.shields.io/badge/LangGraph-1C3C3C?style=flat-square&logo=langgraph&logoColor=white"/>, <img src="https://img.shields.io/badge/crewai-FF5A50?style=flat-square&logo=crewai&logoColor=white"/> |
| LLM | <img src="https://img.shields.io/badge/huggingface-FFD21E?style=flat-square&logo=huggingface&logoColor=black"/>, <img src="https://img.shields.io/badge/openai-412991?style=flat-square&logo=openai&logoColor=white"/> |
| Event Streaming | <img src="https://img.shields.io/badge/kafka-231F20?style=flat-square&logo=apachekafka&logoColor=white"/> |
| Backend | <img src="https://img.shields.io/badge/fastapi-009688?style=flat-square&logo=fastapi&logoColor=white"/> |
| 기타 | AST, SonarQube |
---

## 🧱 아키텍처

<p align="center">
<img src="https://github.com/user-attachments/assets/d4b62eec-ce92-4028-9516-92d6b3ea30a4" alt="ai 아키텍처" width="70%">
</p>

