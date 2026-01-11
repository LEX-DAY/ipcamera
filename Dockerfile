FROM python:3.11-slim

RUN apt update && apt install -y ffmpeg

WORKDIR /app
COPY . .

RUN pip install -r requirements.txt

CMD ["python", "bot/main.py"]
