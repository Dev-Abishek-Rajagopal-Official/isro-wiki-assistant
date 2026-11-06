# One image recipe for every Python component. PROJECT picks the folder whose uv.lock is installed:
#   "isro rag"  (knowledge-base build job)   "isromcp"  (MCP servers)   "isro api"  (FastAPI + LangGraph agent)
# The whole repo is copied because the components import each other by relative path
# (isromcp -> isro rag, isro api -> isro agentic orchestration -> isromcp/mcp_config.py).
FROM python:3.13-slim

ARG PROJECT
ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

RUN pip install --no-cache-dir uv==0.13.7

WORKDIR /app
COPY . /app
RUN cd "/app/${PROJECT}" && uv sync --frozen --no-dev
