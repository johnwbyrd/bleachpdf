#!/usr/bin/env python3
"""Assemble a list of PIL images into a PDF."""
import os, tempfile
from reportlab.pdfgen import canvas

def images_to_pdf(images, output_path, dpi=300):
    """Convert images to PDF at specified DPI."""
    c = canvas.Canvas(output_path)
    for img in images:
        px_w, px_h = img.size
        # Convert pixels to points (72 points per inch)
        pt_w = px_w * 72 / dpi
        pt_h = px_h * 72 / dpi
        c.setPageSize((pt_w, pt_h))
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            img.save(tmp, 'PNG')
            tmp_path = tmp.name
        c.drawImage(tmp_path, 0, 0, pt_w, pt_h)
        c.showPage()
        os.unlink(tmp_path)
    c.save()