FROM python:3.11-slim

WORKDIR /app

# System deps for Playwright Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2 \
    && rm -rf /var/lib/apt/lists/*

COPY qa-office-prod/backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    playwright install chromium --with-deps

# Copy qa-office-prod code
COPY qa-office-prod/backend/ ./backend/
COPY qa-office-prod/agents/ ./agents/
COPY qa-office-prod/services/ ./services/
COPY qa-office-prod/schemas.py qa-office-prod/config/ qa-office-prod/prompts/ ./
COPY qa-office-prod/ .

# Copy qa-os (required by browser_tool.py and report_writer.py)
COPY qa-os/ ./qa-os/

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app/backend
EXPOSE 8005

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8005"]
