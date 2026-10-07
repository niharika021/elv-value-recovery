# ELV Value Recovery Planner: one container for Cloud Run (API, front end, agents).
# Not yet built or deployed; see README "Deploying to Cloud Run".
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY data ./data

# Run as a non-root user. The decision log goes to Firestore on Cloud Run (ELV_STORE=firestore),
# because the container's disk does not survive a restart.
RUN useradd --create-home elv && chown -R elv /srv
USER elv

CMD ["sh", "-c", "exec uvicorn app.web.server:app --host 0.0.0.0 --port ${PORT}"]
