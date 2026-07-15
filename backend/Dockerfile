FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml alembic.ini ./
COPY backend ./backend
RUN pip install --no-cache-dir .
ENV PYTHONPATH=/app/backend
CMD ["uvicorn", "recipecontrol.api:app", "--host", "0.0.0.0", "--port", "8000"]

