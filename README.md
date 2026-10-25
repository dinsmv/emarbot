# EMAR Capital Bot + Mini App

Telegram-бот с базой знаний (Chroma/RAG) и веб-панелью материалов (Telegram Mini App).

## Состав

| Путь | Назначение |
|------|------------|
| `bot.py` | Telegram-бот |
| `knowledge_db/` | Готовая векторная база FAQ |
| `miniapp/` | Frontend Mini App |
| `resources/resources.json` | Каталог материалов |
| `resources/files/` | Фото/PDF/аудио/emoji (видео — отдельно, см. ниже) |
| `deploy/` | systemd, nginx, скрипты деплоя |
| `serve_miniapp.py` | Локальная раздача Mini App |
| `remote_update.sh` | Настройка на VPS после заливки |

## Требования

- Ubuntu 22.04/24.04 (или аналог)
- Python 3.10+
- nginx + certbot (для HTTPS Mini App)
- Ключи в `.env` (см. `.env.example`)

## Быстрый старт на сервере

```bash
# 1. Клон
git clone https://github.com/dinsmv/emarbot.git ~/finish
cd ~/finish

# 2. Секреты
cp .env.example .env
nano .env   # заполнить TELEGRAM_TOKEN, ANTHROPIC_*, JINA_API_KEY, MINIAPP_URL и др.

# 3. Зависимости + сервисы
chmod +x remote_update.sh deploy/*.sh
bash remote_update.sh

# 4. HTTPS для Mini App (пример домена)
# DNS A-запись → IP сервера, затем:
# bash deploy/stabilize_miniapp.sh
# (или ваш certbot + nginx; конфиг собирает stabilize_miniapp.sh)

# 5. Проверка
systemctl status bot
curl -I https://ВАШ_ДОМЕН/
```

`MINIAPP_URL` в `.env` должен быть тем HTTPS-адресом, который открывается с телефона (не localhost).

## Локальный просмотр панели

```bash
cd ~/finish   # или папка клона
python3 serve_miniapp.py
# открыть http://127.0.0.1:8765/
```

## Видеофайлы

В git **не входят** большие `.mp4` / `.MOV` (лимиты GitHub).  
Каталог уже ссылается на YouTube / RuTube / VK Video — для работы панели и бота локальные ролики не обязательны.

Если нужны локальные файлы на сервере — положите их в `resources/files/` вручную.

## Пересборка базы знаний (опционально)

Если нужно пересобрать `knowledge_db` с нуля (нужны Jina embeddings):

```bash
source .venv/bin/activate
python3 build_database.py
systemctl restart bot
```

Добавить новые Q&A без полной пересборки:

```bash
python3 append_qa_to_db.py video_links_qa.txt
python3 append_qa_to_db.py exchanger_qa.txt
```

## Cloudflare Tunnel (если входящий HTTPS на VPS недоступен)

```bash
bash deploy/setup_cf_tunnel.sh
# пропишет MINIAPP_URL вида https://….trycloudflare.com/
systemctl restart bot
```

Для продакшена лучше named tunnel / свой домен за Cloudflare, не `trycloudflare`.

## Полезные команды

```bash
journalctl -u bot -n 50 --no-pager
systemctl restart bot
bash deploy/stabilize_miniapp.sh
```
