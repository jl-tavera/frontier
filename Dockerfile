FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
# rapidocr pulls in the full opencv-python, whose cv2 needs X11/GL libs the slim image lacks;
# skip it so only the locked opencv-python-headless provides cv2
RUN uv sync --frozen --no-dev --no-install-package opencv-python
COPY . .
ENV PATH="/app/.venv/bin:$PATH" PORT=8000
# Fail the build, not the start, when the app can't import
RUN python -c "import app.main"
# The container sees all 48 host CPUs; uncapped, OCR and BLAS spawn a thread per CPU on a small share (#88).
# app/perception/ocr.py passes OMP_NUM_THREADS on to onnxruntime.
ENV OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4
# One worker: task state and RFB sessions live in-process (solution.md §3.4)
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1"]
