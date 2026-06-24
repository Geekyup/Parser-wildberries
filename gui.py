"""
Wildberries Parser — графический интерфейс.

Запуск:
    python gui.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from wb_parser import ScrapingCancelled, run_scraping


class WBParserApp:
    """Главное окно приложения WB Parser."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Wildberries Parser")
        self.root.geometry("740x600")
        self.root.minsize(640, 500)

        self.cookies_path: str | None = None
        self.output_path: str | None = None
        self.worker_thread: threading.Thread | None = None
        self.cancel_requested = False

        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        # Ссылка на категорию
        frm_url = ttk.LabelFrame(self.root, text="Ссылка на категорию Wildberries")
        frm_url.pack(fill="x", **pad)
        self.url_entry = ttk.Entry(frm_url, font=("Segoe UI", 10))
        self.url_entry.pack(fill="x", padx=8, pady=8)
        self.url_entry.insert(0, "https://www.wildberries.ru/catalog/...")

        # Поисковый запрос (опционально)
        frm_query = ttk.LabelFrame(self.root, text="Поисковый запрос (опционально, заменяет автоопределение)")
        frm_query.pack(fill="x", **pad)
        self.query_entry = ttk.Entry(frm_query, font=("Segoe UI", 10))
        self.query_entry.pack(fill="x", padx=8, pady=8)

        # Параметры
        frm_params = ttk.LabelFrame(self.root, text="Параметры")
        frm_params.pack(fill="x", **pad)

        row1 = ttk.Frame(frm_params)
        row1.pack(fill="x", padx=8, pady=4)
        ttk.Label(row1, text="Кол-во товаров:").pack(side="left")
        self.count_var = tk.IntVar(value=1000)
        ttk.Spinbox(row1, from_=1, to=50000, width=7, textvariable=self.count_var).pack(side="left", padx=8)
        ttk.Label(row1, text="Страниц на сегмент:").pack(side="left", padx=(16, 0))
        self.pages_var = tk.IntVar(value=4)
        ttk.Spinbox(row1, from_=1, to=20, width=4, textvariable=self.pages_var).pack(side="left", padx=8)
        ttk.Label(row1, text="Задержка (сек):").pack(side="left", padx=(16, 0))
        self.delay_var = tk.DoubleVar(value=0.25)
        ttk.Spinbox(row1, from_=0.0, to=10.0, increment=0.05, width=5, textvariable=self.delay_var, format="%.2f").pack(side="left", padx=8)

        row2 = ttk.Frame(frm_params)
        row2.pack(fill="x", padx=8, pady=4)
        ttk.Label(row2, text="Цена от:").pack(side="left")
        self.price_min_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.price_min_var, width=8).pack(side="left", padx=4)
        ttk.Label(row2, text="до:").pack(side="left")
        self.price_max_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.price_max_var, width=8).pack(side="left", padx=4)
        ttk.Label(row2, text="(руб, оба пустых = автодиапазон)", foreground="#888").pack(side="left", padx=8)

        row3 = ttk.Frame(frm_params)
        row3.pack(fill="x", padx=8, pady=4)
        ttk.Label(row3, text="cookies.txt:").pack(side="left")
        self.cookies_label = ttk.Label(row3, text="(не выбран — нужен для парсинга)", foreground="#888")
        self.cookies_label.pack(side="left", padx=8)
        ttk.Button(row3, text="Выбрать...", command=self._choose_cookies).pack(side="right")

        row4 = ttk.Frame(frm_params)
        row4.pack(fill="x", padx=8, pady=4)
        ttk.Label(row4, text="Сохранить в:").pack(side="left")
        self.output_label = ttk.Label(row4, text="wb_results.xlsx (в папке программы)", foreground="#888")
        self.output_label.pack(side="left", padx=8)
        ttk.Button(row4, text="Выбрать...", command=self._choose_output).pack(side="right")

        # Кнопки
        frm_actions = ttk.Frame(self.root)
        frm_actions.pack(fill="x", **pad)
        self.start_btn = ttk.Button(frm_actions, text="▶ Начать парсинг", command=self._on_start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(frm_actions, text="■ Остановить", command=self._on_stop, state="disabled")
        self.stop_btn.pack(side="left", padx=8)
        self.open_file_btn = ttk.Button(frm_actions, text="Открыть Excel", command=self._open_result, state="disabled")
        self.open_file_btn.pack(side="right")

        # Прогресс
        frm_progress = ttk.Frame(self.root)
        frm_progress.pack(fill="x", **pad)
        self.progress = ttk.Progressbar(frm_progress, mode="determinate")
        self.progress.pack(fill="x")
        self.status_label = ttk.Label(frm_progress, text="Готов к запуску.")
        self.status_label.pack(anchor="w", pady=(4, 0))

        # Лог
        frm_log = ttk.LabelFrame(self.root, text="Журнал")
        frm_log.pack(fill="both", expand=True, **pad)
        self.log_text = tk.Text(frm_log, height=8, state="disabled", wrap="word", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True, padx=4, pady=4)

    # ------------------------------------------------------------------
    # Диалоги
    # ------------------------------------------------------------------

    def _choose_cookies(self):
        path = filedialog.askopenfilename(
            title="Выбери файл cookies.txt",
            filetypes=[("Текстовые файлы", "*.txt"), ("Все файлы", "*.*")],
        )
        if path:
            self.cookies_path = path
            self.cookies_label.config(text=os.path.basename(path), foreground="#000")

    def _choose_output(self):
        path = filedialog.asksaveasfilename(
            title="Куда сохранить результат",
            defaultextension=".xlsx",
            initialfile="wb_results.xlsx",
            filetypes=[("Excel файл", "*.xlsx")],
        )
        if path:
            self.output_path = path
            self.output_label.config(text=os.path.basename(path), foreground="#000")

    def _open_result(self):
        if self.output_path and os.path.exists(self.output_path):
            if sys.platform.startswith("win"):
                os.startfile(self.output_path)
            elif sys.platform == "darwin":
                subprocess.run(["open", self.output_path])
            else:
                subprocess.run(["xdg-open", self.output_path])

    # ------------------------------------------------------------------
    # Запуск / остановка
    # ------------------------------------------------------------------

    def _on_start(self):
        url = self.url_entry.get().strip()
        if not url.startswith("https://"):
            messagebox.showerror("Ошибка", "Вставь корректную ссылку на wildberries.ru")
            return

        price_min = self._parse_price(self.price_min_var.get())
        price_max = self._parse_price(self.price_max_var.get())
        if (price_min is None) != (price_max is None):
            messagebox.showerror("Ошибка", "Укажи оба поля цены или оставь оба пустыми.")
            return
        if price_min is not None and price_min > price_max:
            messagebox.showerror("Ошибка", "Цена «от» не может быть больше цены «до».")
            return

        output_file = self.output_path or "wb_results.xlsx"
        self.output_path = output_file
        manual_query = self.query_entry.get().strip() or None

        self.cancel_requested = False
        self._set_running(True)
        self._clear_log()
        self.progress.config(maximum=self.count_var.get(), value=0)

        self.worker_thread = threading.Thread(
            target=self._run_worker,
            args=(url, manual_query, output_file, price_min, price_max),
            daemon=True,
        )
        self.worker_thread.start()

    def _on_stop(self):
        self.cancel_requested = True
        self._append_log("Останавливаю после текущего сегмента...")

    def _run_worker(self, url, manual_query, output_file, price_min, price_max):
        try:
            output_path, count = run_scraping(
                category_url=url,
                output_file=output_file,
                target_count=self.count_var.get(),
                max_pages=self.pages_var.get(),
                delay=self.delay_var.get(),
                price_min=price_min,
                price_max=price_max,
                manual_query=manual_query,
                cookies_file=self.cookies_path,
                log_callback=lambda msg: self.root.after(0, self._append_log, msg),
                progress_callback=lambda cur, total: self.root.after(0, self._update_progress, cur, total),
                should_cancel=lambda: self.cancel_requested,
            )
            self.root.after(0, self._on_finished, count, str(output_path))
        except ScrapingCancelled:
            self.root.after(0, self._on_cancelled)
        except Exception as e:
            self.root.after(0, self._on_error, str(e))

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------

    def _append_log(self, msg: str):
        self.log_text.config(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")
        self.status_label.config(text=msg)

    def _clear_log(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    def _update_progress(self, current: int, total: int):
        self.progress.config(maximum=total, value=current)

    def _set_running(self, running: bool):
        self.start_btn.config(state="disabled" if running else "normal")
        self.stop_btn.config(state="normal" if running else "disabled")
        self.open_file_btn.config(state="disabled")

    def _on_finished(self, count: int, path: str):
        self._set_running(False)
        self.open_file_btn.config(state="normal" if count else "disabled")
        self.status_label.config(text=f"Готово! Собрано товаров: {count}")
        if count:
            messagebox.showinfo("Готово", f"Собрано {count} товаров.\nФайл: {path}")
        else:
            messagebox.showwarning("Нет данных", "Не удалось собрать ни одного товара. Смотри журнал.")

    def _on_cancelled(self):
        self._set_running(False)
        self.status_label.config(text="Остановлено пользователем.")

    def _on_error(self, error_msg: str):
        self._set_running(False)
        self.status_label.config(text="Произошла ошибка.")
        messagebox.showerror("Ошибка", f"Что-то пошло не так:\n{error_msg}")

    @staticmethod
    def _parse_price(value: str) -> int | None:
        value = value.strip()
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            return None


def main():
    root = tk.Tk()
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass
    WBParserApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
