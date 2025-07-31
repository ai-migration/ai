import streamlit as st
from openai import OpenAI

st.title("전자정부 프레임워크 챗봇")

# OpenAI client 초기화
client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

# 모델 기본값
if "openai_model" not in st.session_state:
    st.session_state["openai_model"] = "gpt-3.5-turbo"

# 대화 내역 초기화
if "messages" not in st.session_state:
    st.session_state.messages = []

# 이전 대화 렌더링
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 사용자 입력 처리
if prompt := st.chat_input("What is up?"):
    # 1) 사용자 메시지 저장 및 표시
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 2) OpenAI API 호출
    with st.spinner("Thinking..."):
        response = client.chat.completions.create(
            model=st.session_state["openai_model"],
            messages=st.session_state.messages
        )
        assistant_reply = response.choices[0].message.content

    # 3) assistant 메시지 저장 및 표시
    st.session_state.messages.append({"role": "assistant", "content": assistant_reply})
    with st.chat_message("assistant"):
        st.markdown(assistant_reply)

