FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

RUN pip install uv

COPY pyproject.toml .

# Install dependencies using uv with --system flag (no venv in Docker)
RUN uv pip install --system -e .

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
