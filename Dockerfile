FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -r -u 1000 agent && mkdir -p data && chown -R agent /app
USER agent
EXPOSE 8888
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8888/api/health', timeout=4)"
CMD ["python", "-m", "src.agent"]
