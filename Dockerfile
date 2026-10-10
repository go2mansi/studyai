FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=5001
CMD ["sh", "-c", "python manage.py init-db && gunicorn -b 0.0.0.0:${PORT} --timeout 90 app:app"]
