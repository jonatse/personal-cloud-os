"""Reusable UI components."""
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional


class StatusIndicator:
    """A status indicator widget."""
    
    def __init__(self, parent, label: str = "", color: str = "#a6e3a1"):
        """Initialize status indicator."""
        self.frame = tk.Frame(parent, bg=parent.cget("bg"))
        
        self._canvas = tk.Canvas(
            self.frame,
            width=10,
            height=10,
            bg=parent.cget("bg"),
            highlightthickness=0
        )
        self._canvas.pack(side=tk.LEFT, padx=(0, 5))
        
        self._circle = self._canvas.create_oval(2, 2, 8, 8, fill=color, outline="")
        
        self._label = tk.Label(
            self.frame,
            text=label,
            bg=parent.cget("bg")
        )
        self._label.pack(side=tk.LEFT)
        
        self._color = color
    
    def pack(self, **kwargs):
        """Pack the widget."""
        self.frame.pack(**kwargs)
    
    def set_color(self, color: str):
        """Set indicator color."""
        self._canvas.itemconfigure(self._circle, fill=color)
        self._color = color
    
    def set_text(self, text: str):
        """Set label text."""
        self._label.config(text=text)


class Button(tk.Button):
    """Styled button widget."""
    
    def __init__(self, parent, **kwargs):
        """Initialize button."""
        defaults = {
            "bg": "#45475a",
            "fg": "#cdd6f4",
            "activebackground": "#585b70",
            "activeforeground": "#cdd6f4",
            "relief": tk.FLAT,
            "cursor": "hand2",
            "font": ("Helvetica", 10)
        }
        defaults.update(kwargs)
        super().__init__(parent, **defaults)


class Card(tk.Frame):
    """Card-style container widget."""
    
    def __init__(self, parent, title: str = "", **kwargs):
        """Initialize card."""
        bg = kwargs.pop("bg", "#313244")
        super().__init__(parent, bg=bg, **kwargs)
        
        if title:
            title_label = tk.Label(
                self,
                text=title,
                font=("Helvetica", 12, "bold"),
                fg="#cdd6f4",
                bg=bg
            )
            title_label.pack(anchor=tk.W, padx=10, pady=(10, 5))
        
        self._content = tk.Frame(self, bg=bg)
        self._content.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
    
    @property
    def content(self):
        """Get content frame."""
        return self._content


class ProgressBar:
    """Progress bar widget."""
    
    def __init__(self, parent, **kwargs):
        """Initialize progress bar."""
        self._var = tk.DoubleVar()
        self._bar = ttk.Progressbar(
            parent,
            variable=self._var,
            mode="determinate",
            **kwargs
        )
    
    def pack(self, **kwargs):
        """Pack the widget."""
        self._bar.pack(**kwargs)
    
    def set_progress(self, value: float, maximum: float = 100):
        """Set progress value."""
        self._var.set((value / maximum) * 100)
    
    def reset(self):
        """Reset progress."""
        self._var.set(0)
