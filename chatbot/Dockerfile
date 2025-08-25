FROM python:latest


COPY requirements.txt .
RUN pip install -r requirements.txt
# RUN pip install --no-cache-dir -r requirements.txt

COPY app ./ai/chatbot/app
COPY rag_index ./ai/chatbot/rag_index

WORKDIR /ai

CMD ["uvicorn", "chatbot.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
