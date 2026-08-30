FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/import_csv_to_monday.py ./import_csv_to_monday.py
COPY frontend ./frontend

# Env vars are supplied at deploy time (see .env.example):
#   MONDAY_API_TOKEN, GEMINI_API_KEY, DEALS_BOARD_ID, WORK_ORDERS_BOARD_ID
ENV PORT=8000
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
