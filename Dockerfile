FROM python:3.11-slim

WORKDIR /app

# Skip Playwright browser download — browser tests run via external runner
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend and shared code
COPY backend/ ./backend/
COPY agents/ ./agents/
COPY services/ ./services/
COPY schemas.py config/ prompts/ ./
COPY . .

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app/backend
EXPOSE 8005

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8005"]
