FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home selection && mkdir /appdata /logs && chown selection:selection /appdata /logs
COPY app ./app
COPY main.py .
COPY config/config.example.yaml /app/config/config.yaml
USER selection
ENTRYPOINT ["python", "main.py"]
