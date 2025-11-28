# Base image - Python 3.10 ব্যবহার করা হলো
FROM python:3.10-slim

# Working directory তৈরি
WORKDIR /app

# Dependency ফাইল কপি করা
COPY requirements.txt .

# Python dependency install করা
RUN pip install --no-cache-dir -r requirements.txt

# App এর সব ফাইল কপি করা
COPY . .

# Port expose করা (আপনার FastAPI বা Flask app এর জন্য)
EXPOSE 8000

# Container run করার সময় এই কমান্ড execute হবে
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
