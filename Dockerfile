# 1. Asosiy image
FROM python:3.11-slim

# 2. Ishchi katalog
WORKDIR /app

# 3. Talablarni o‘rnatish
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# 4. Bot fayllarni nusxalash
COPY . .

# 5. Botni ishga tushurish
CMD ["python", "main.py"]
