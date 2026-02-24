"""
Entry point for Hugging Face Spaces or: gradio app.py

When deployed on HF Spaces, this file is used as the Gradio app.
Locally, prefer: python ui.py
"""
from ui import build_ui

demo = build_ui()

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
