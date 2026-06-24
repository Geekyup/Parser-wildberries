# wb-parser

Парсер товаров Wildberries. Принимает ссылку на категорию или поисковый запрос, собирает нужное количество товаров и сохраняет в Excel.

## Что собирает

Название, бренд, магазин, рейтинг товара, рейтинг продавца, количество отзывов, цена, ссылка.

## Установка

```bash
git clone https://github.com/your-username/wb-parser.git
cd wb-parser
pip install -r requirements.txt
```

## Авторизация

Нужны два cookie с сайта WB: `x_wbaas_token` и `_wbauid`. Передать любым способом:

**Вариант 1 — файл `.env`** (рекомендуется)
```
WB_X_WBAAS_TOKEN=ваш_токен
WB_WBAUID=ваш_uid
```

**Вариант 2 — `cookies.txt`**
Экспортируйте cookies в формате Netscape через расширение EditThisCookie или `curl --cookie-jar`.

**Вариант 3 — переменные окружения**
```bash
export WB_X_WBAAS_TOKEN=ваш_токен
export WB_WBAUID=ваш_uid
```

## Запуск

```bash
# По ссылке на категорию
python main.py https://www.wildberries.ru/catalog/muzhchinam/odezhda/bryuki-i-shorty

# По поисковому запросу
python main.py --query "джинсы мужские" --target-count 500

# С фильтром по цене
python main.py URL --price-min 1000 --price-max 5000
```

Результат сохраняется в `.xlsx` рядом с `main.py`.

## Параметры

| Параметр | По умолчанию | Описание |
|---|---|---|
| `--query` | — | Поисковый запрос (вместо URL) |
| `--target-count` | 1000 | Сколько товаров собрать |
| `--price-min` / `--price-max` | — | Ограничение по цене (оба обязательны) |
| `--output-prefix` | — | Имя выходного файла без `.xlsx` |
| `--max-pages` | 4 | Страниц на один ценовой сегмент |
| `--delay` | 0.25 | Пауза между запросами (сек) |
| `--log-level` | INFO | DEBUG / INFO / WARNING / ERROR |

## Структура проекта

```
wb-parser/
├── main.py              # точка входа, CLI
├── requirements.txt
├── wb_parser/
│   ├── config.py        # константы и dataclasses настроек
│   ├── credentials.py   # загрузка cookies.txt и .env
│   ├── utils.py         # мелкие утилиты
│   ├── client.py        # HTTP-клиент к WB API
│   ├── collector.py     # логика сбора и дедупликации
│   └── exporter.py      # экспорт в Excel
```
