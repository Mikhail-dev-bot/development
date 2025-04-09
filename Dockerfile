FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    libmupdf-dev \
    libmagic-dev \
    build-essential \
    poppler-utils \
    tesseract-ocr \
    libgl1 \
    && apt-get clean

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1

CMD ["python", "TD_BOT.py"]
