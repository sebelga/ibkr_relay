FROM python:3.11-slim

WORKDIR /app

COPY services/relay_core/requirements.txt .
RUN pip install --no-cache-dir --root-user-action=ignore --upgrade pip==26.1.2
RUN pip install --no-cache-dir --root-user-action=ignore -r requirements.txt

COPY services/relay_core/ ./relay_core/
COPY services/relays/ ./relays/
COPY services/shared/ ./shared/

CMD ["python", "-u", "-m", "relay_core.main"]
