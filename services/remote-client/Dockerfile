FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py ./
COPY models_remote_client.py ./
COPY client/ client/
COPY routes/ routes/

CMD ["python", "-u", "main.py"]
