"""Gradio UI: type a description, see the top-6 meme images.

Run locally:   python -m search.app
Run on Colab:  python -m search.app  (launches with a public share link)
"""
import os
import sys
import gradio as gr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import resolve_image_path, TOP_K
from search.retrieve import MemeSearcher

searcher = MemeSearcher()


def find(query, k=TOP_K):
    if not query or not query.strip():
        return [], ["Type what kind of meme you want."]
    results = searcher.search(query, k=k)
    images, captions = [], []
    for r in results:
        path = resolve_image_path(r.get("image_path"))
        if path and os.path.exists(path):
            images.append(path)
        else:
            # fall back to remote url (works where network is available)
            images.append(r.get("image_url") or "")
        captions.append(
            f"{r['score']:.3f} | {r.get('title')}\n{r.get('source_sub')}"
        )
    return images, captions


with gr.Blocks(title="MakeMeMeme") as demo:
    gr.Markdown("# MakeMeMeme - describe a meme, get the best matches")
    with gr.Row():
        box = gr.Textbox(
            label="What kind of meme do you want?",
            placeholder="e.g. when you pretend to work but do nothing",
        )
        k = gr.Slider(1, 10, value=TOP_K, step=1, label="Number of results")
    btn = gr.Button("Find memes")
    with gr.Row():
        gallery = gr.Gallery(label="Results", columns=3, height="auto")
        cap = gr.Textbox(label="Details", lines=8)
    btn.click(fn=find, inputs=[box, k], outputs=[gallery, cap])
    box.submit(fn=find, inputs=[box, k], outputs=[gallery, cap])

    # expose a public link when running on Colab / remote
    share = os.environ.get("MAKEMEME_SHARE", "0") == "1"


if __name__ == "__main__":
    demo.launch(share=share, server_name="0.0.0.0", server_port=7860)
