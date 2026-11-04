FROM python:3.12-alpine

WORKDIR /app
COPY attack.py .

# No USER: the node decides who a task runs as, and that is one of the things it checks.
ENTRYPOINT ["python", "/app/attack.py"]
