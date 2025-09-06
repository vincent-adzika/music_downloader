# Use Python 3.12 base image
FROM python:3.12-slim

# Install system dependencies (FFmpeg + curl + others)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy files
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run the bot
CMD ["python", "bot.py"]
