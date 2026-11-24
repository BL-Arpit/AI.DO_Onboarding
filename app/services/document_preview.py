"""Bounded rendering of stored PDF and image uploads for authenticated review."""

import io
from contextlib import closing

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError


def render_document_page(content, page=1):
    content = bytes(content)
    if content.startswith(b"%PDF-"):
        import pypdfium2 as pdfium

        try:
            with pdfium.PdfDocument(content) as document:
                count = len(document)
                if page < 1 or page > count:
                    raise HTTPException(404, "Document page unavailable.")
                with closing(document.get_page(page - 1)) as pdf_page:
                    width, height = pdf_page.get_size()
                    if min(width, height) <= 0:
                        raise ValueError("Invalid page dimensions")
                    scale = min(2.0, 1600 / max(width, height))
                    bitmap = pdf_page.render(scale=scale)
                    try:
                        image = bitmap.to_pil().copy()
                    finally:
                        bitmap.close()
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(422, "The PDF preview could not be rendered.") from None
    else:
        if page != 1:
            raise HTTPException(404, "Document page unavailable.")
        count = 1
        try:
            with Image.open(io.BytesIO(content)) as original:
                if original.width * original.height > 40_000_000:
                    raise HTTPException(413, "The image exceeds the preview pixel limit.")
                image = ImageOps.exif_transpose(original).convert("RGB")
                image.thumbnail((1600, 1600))
        except HTTPException:
            raise
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            raise HTTPException(422, "The image preview could not be rendered.") from None
    output = io.BytesIO()
    image.save(output, format="PNG")
    image.close()
    return output.getvalue(), count
