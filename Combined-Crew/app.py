"""
Sole entry point for Hugging Face Spaces, Render, and local runs.

- HF Spaces: Set App file to Combined-Crew/app.py in Space Settings.
- Render: Uses PORT from env (Render sets it).
- Locally: python ui.py or gradio app.py

See DEPLOY.md for deployment instructions.
"""
import os

from ui import build_ui

demo = build_ui()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    demo.launch(server_name="0.0.0.0", server_port=port)
