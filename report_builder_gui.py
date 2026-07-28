"""
A simple double-click program for turning any extracted JSON file into a
finished Excel report -- no renaming to listings.json, no typing commands.

HOW TO RUN:
    Double-click "Open Report Builder.bat" in this same folder.
    (Or: python report_builder_gui.py, if you prefer the terminal.)

HOW TO USE:
    Click "Choose JSON File...", pick ANY .json file with any name, and
    the Excel report saves automatically right next to it, named after
    the same file (e.g. "chat1.json" -> "chat1_report.xlsx").
"""
import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox

from pipeline.match import find_matches, fill_missing_demand_contact
from pipeline.report import build_report


def process_file():
    json_path = filedialog.askopenfilename(
        title="Choose your extracted JSON file",
        filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
    )
    if not json_path:
        return  # user clicked cancel

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            rows = json.load(f)

        rows = fill_missing_demand_contact(rows)
        matches = find_matches(rows)

        base_name = os.path.splitext(os.path.basename(json_path))[0]
        output_path = os.path.join(os.path.dirname(json_path), f"{base_name}_report.xlsx")

        build_report(rows, matches, output_path)

        open_folder = messagebox.askyesno(
            "Done!",
            f"Report built successfully.\n\n"
            f"{len(rows)} listings, {len(matches)} matches.\n\n"
            f"Saved as:\n{os.path.basename(output_path)}\n\n"
            f"Open the folder now?"
        )
        if open_folder:
            os.startfile(os.path.dirname(output_path))

    except Exception as e:
        messagebox.showerror("Something went wrong", str(e))


def main():
    root = tk.Tk()
    root.title("ProBroker Report Builder")
    root.geometry("440x240")
    root.configure(bg="#0B0A08")
    root.resizable(False, False)

    tk.Label(
        root, text="ProBroker Report Builder",
        font=("Segoe UI", 16, "bold"), bg="#0B0A08", fg="#F5F1E7"
    ).pack(pady=(34, 10))

    tk.Label(
        root, text="Pick any extracted JSON file.\nThe Excel report saves automatically right next to it.",
        font=("Segoe UI", 10), bg="#0B0A08", fg="#B8B2A2", justify="center"
    ).pack(pady=(0, 26))

    tk.Button(
        root, text="Choose JSON File...", command=process_file,
        font=("Segoe UI", 12, "bold"), bg="#A67C3D", fg="#0B0A08",
        activebackground="#D9AD5F", relief="flat", padx=22, pady=13, cursor="hand2"
    ).pack()

    root.mainloop()


if __name__ == "__main__":
    main()
