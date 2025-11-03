# Сначало мы должны произвести нужных зависимостей: pip install ttkbootstrap psutil
import os, sys, threading, queue, fnmatch, platform, subprocess, csv
from datetime import datetime
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
import psutil
import tkinter.filedialog as fd
from tkinter import messagebox

def open_path(path):
    try:
        if platform.system() == "Windows":
            os.startfile(path)
        elif platform.system() == "Darwin":
            subprocess.run(["open", path])
        else:
            subprocess.run(["xdg-open", path])
    except Exception as e:
        messagebox.showerror("Ошибка", str(e))

def open_in_explorer(path):
    try:
        if platform.system() == "Windows":
            subprocess.run(["explorer", "/select,", os.path.normpath(path)])
        elif platform.system() == "Darwin":
            subprocess.run(["open", "-R", path])
        else:
            open_path(os.path.dirname(path))
    except Exception as e:
        messagebox.showerror("Ошибка", str(e))

def get_roots():
    roots = []
    for part in psutil.disk_partitions(all=False):
        roots.append(part.mountpoint)
    if not roots:
        roots = [os.path.abspath(os.sep)]
    return roots

def readable_size(size):
    for unit in ["Б", "КБ", "МБ", "ГБ"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} ТБ"

class SearchThread(threading.Thread):
    def __init__(self, pattern, roots, filters, q_results, stop_event):
        super().__init__(daemon=True)
        self.pattern = pattern
        self.roots = roots
        self.filters = filters
        self.q = q_results
        self.stop = stop_event

    def run(self):
        content = self.filters.get("content")
        min_size = self.filters.get("min_size")
        max_size = self.filters.get("max_size")
        for root in self.roots:
            for dirpath, _, files in os.walk(root):
                if self.stop.is_set():
                    return
                for name in files:
                    full = os.path.join(dirpath, name)
                    if not fnmatch.fnmatch(name.lower(), self.pattern.lower()):
                        continue
                    try:
                        st = os.stat(full)
                    except Exception:
                        continue
                    if min_size and st.st_size < min_size:
                        continue
                    if max_size and st.st_size > max_size:
                        continue
                    if content:
                        try:
                            with open(full, "r", errors="ignore") as f:
                                data = f.read()
                                if content.lower() not in data.lower():
                                    continue
                        except Exception:
                            continue
                    self.q.put({
                        "path": full,
                        "size": st.st_size,
                        "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                    })
        self.q.put(None)

class FileScannerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("FileScanner")
        self.q = queue.Queue()
        self.stop_event = threading.Event()
        self.thread = None
        self.roots = get_roots()

        style = ttk.Style(theme="darkly")

        frm_top = ttk.Frame(root, padding=10)
        frm_top.pack(fill=X)

        ttk.Label(frm_top, text="Название файла:").pack(side=LEFT)
        self.name_entry = ttk.Entry(frm_top, width=30)
        self.name_entry.pack(side=LEFT, padx=5)

        ttk.Label(frm_top, text="Расширение:").pack(side=LEFT, padx=(10, 0))

        extensions = [
            "Все",
            ".exe", ".txt", ".pdf", ".docx", ".xlsx", ".jpg", ".png",
            ".mp3", ".mp4", ".zip", ".rar", ".py", ".cpp", ".json", ".csv",
        ]
        self.ext_var = ttk.StringVar(value="Все")
        self.ext_combo = ttk.Combobox(frm_top, textvariable=self.ext_var, values=extensions, width=8, bootstyle=INFO)
        self.ext_combo.pack(side=LEFT, padx=5)

        ttk.Button(frm_top, text="Поиск", bootstyle=SUCCESS, command=self.start_search).pack(side=LEFT, padx=5)
        ttk.Button(frm_top, text="Стоп", bootstyle=DANGER, command=self.stop_search).pack(side=LEFT, padx=5)

        frm_filters = ttk.Labelframe(root, text="Фильтры", padding=10)
        frm_filters.pack(fill=X, padx=10, pady=5)

        ttk.Label(frm_filters, text="Текст в файле:").pack(side=LEFT)
        self.content_var = ttk.Entry(frm_filters, width=30)
        self.content_var.pack(side=LEFT, padx=5)

        self.min_var = ttk.Entry(frm_filters, width=10)
        ttk.Label(frm_filters, text="Мин. размер (КБ):").pack(side=LEFT)
        self.min_var.pack(side=LEFT, padx=5)

        self.max_var = ttk.Entry(frm_filters, width=10)
        ttk.Label(frm_filters, text="Макс. размер (КБ):").pack(side=LEFT)
        self.max_var.pack(side=LEFT, padx=5)

        ttk.Label(frm_filters, text=f"Диски: {', '.join(self.roots)}").pack(side=LEFT, padx=10)

        frm_results = ttk.Frame(root, padding=5)
        frm_results.pack(fill=BOTH, expand=True)

        cols = ("path", "size", "mtime")
        self.tree = ttk.Treeview(frm_results, columns=cols, show="headings")
        for c, text in zip(cols, ["Путь", "Размер", "Изменён"]):
            self.tree.heading(c, text=text)
        self.tree.column("path", width=600)
        self.tree.column("size", width=100)
        self.tree.column("mtime", width=150)
        self.tree.pack(fill=BOTH, expand=True, side=LEFT)
        sb = ttk.Scrollbar(frm_results, command=self.tree.yview)
        sb.pack(side=LEFT, fill=Y)
        self.tree.config(yscrollcommand=sb.set)
        self.tree.bind("<Double-1>", lambda e: self.open_selected())

        self.menu = ttk.Menu(root, tearoff=0)
        self.menu.add_command(label="Открыть", command=self.open_selected)
        self.menu.add_command(label="Открыть в Проводнике", command=self.open_in_explorer)
        self.menu.add_separator()
        self.menu.add_command(label="Удалить", command=self.delete_selected)
        self.menu.add_command(label="Экспорт CSV", command=self.export_csv)
        self.tree.bind("<Button-3>", self.show_menu)

        self.status = ttk.Label(root, text="Готов", anchor=W)
        self.status.pack(fill=X)

    def start_search(self):
        name = self.name_entry.get().strip()
        ext = self.ext_var.get().strip()
        if not name and ext == "Все":
            messagebox.showwarning("Ошибка", "Введите название или выберите расширение.")
            return

        if ext == "Все":
            pattern = f"*{name}*"
        else:
            pattern = f"{name}{ext}"

        for i in self.tree.get_children():
            self.tree.delete(i)

        filters = {
            "content": self.content_var.get().strip(),
            "min_size": int(self.min_var.get()) * 1024 if self.min_var.get().isdigit() else None,
            "max_size": int(self.max_var.get()) * 1024 if self.max_var.get().isdigit() else None,
        }
        self.stop_event.clear()
        self.thread = SearchThread(pattern, self.roots, filters, self.q, self.stop_event)
        self.thread.start()
        self.root.after(200, self.update_results)
        self.status.config(text=f"Поиск: {pattern}")

    def update_results(self):
        try:
            while True:
                item = self.q.get_nowait()
                if item is None:
                    self.status.config(text="Поиск завершён")
                    return
                self.tree.insert("", END, values=(item["path"], readable_size(item["size"]), item["mtime"]))
        except queue.Empty:
            if not self.stop_event.is_set():
                self.root.after(200, self.update_results)

    def stop_search(self):
        self.stop_event.set()
        self.status.config(text="Поиск остановлен")

    def get_selected(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return self.tree.item(sel[0], "values")[0]

    def open_selected(self):
        p = self.get_selected()
        if p: open_path(p)

    def open_in_explorer(self):
        p = self.get_selected()
        if p: open_in_explorer(p)

    def delete_selected(self):
        p = self.get_selected()
        if not p: return
        if messagebox.askyesno("Удалить", f"Удалить файл?\n{p}"):
            try:
                os.remove(p)
                self.tree.delete(self.tree.selection()[0])
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

    def export_csv(self):
        path = fd.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path: return
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Путь", "Размер", "Изменён"])
            for row in self.tree.get_children():
                writer.writerow(self.tree.item(row)["values"])
        messagebox.showinfo("Экспорт", f"Сохранено: {path}")

    def show_menu(self, e):
        try:
            iid = self.tree.identify_row(e.y)
            if iid:
                self.tree.selection_set(iid)
                self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()


if __name__ == "__main__":
    root = ttk.Window(title="FileScanner", themename="darkly")
    app = FileScannerApp(root)
    root.mainloop()
