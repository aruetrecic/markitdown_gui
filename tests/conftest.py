import os

# El limiter cuenta por IP; en los tests todo sale de 127.0.0.1, así que un
# límite real sumaría las llamadas entre tests y provocaría 429 espurios.
# Se apaga globalmente; el test dedicado de rate limiting instancia su propio
# Limiter activo para verificar el 429.
os.environ.setdefault("RATE_LIMIT_ENABLED", "0")
