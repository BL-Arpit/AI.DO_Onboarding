from pathlib import Path

import cv2
import numpy as np
import pypdfium2 as pdfium
from PIL import Image, ImageEnhance, ImageOps

from app.extraction.documents.models.documents import DocumentType
from app.extraction.settings import MAX_IMAGE_PIXELS, MAX_PDF_PAGES


class OCRPreprocessor:
    """Create OCR-ready image variants without modifying the source."""

    TARGET_WIDTH = 1800
    MAX_SCALE = 3

    def preprocess_for_document(
        self, file_path: str | Path, document_type: DocumentType | None
    ) -> list[Image.Image]:
        """Build a small, document-specific set of OCR views for the API hot path.

        The exhaustive variant set remains available to legacy/debug callers.
        API extraction uses these focused views so OCR latency does not grow
        linearly with every threshold and PSM combination.
        """
        path = Path(file_path)
        if path.suffix.lower() == ".pdf":
            variants = self.preprocess(path)
            # Retain the first page and its grayscale view; extraction should
            # be bounded for the interactive API request.
            kept, discarded = variants[:2], variants[2:]
            for image in discarded:
                image.close()
            return kept

        with Image.open(path) as source:
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise ValueError("Image exceeds the configured pixel limit.")
            original = ImageOps.exif_transpose(source).convert("RGB")

        try:
            width, height = original.size
            gray = ImageOps.autocontrast(ImageOps.grayscale(original))
            if gray.width > 1800:
                scale = 1800 / gray.width
                resized = gray.resize(
                    (1800, max(1, round(gray.height * scale))),
                    Image.Resampling.LANCZOS,
                )
                gray.close()
                gray = resized
            variants = [gray.copy()]
            if document_type is None and width > height:
                # High-contrast header view helps identify coloured/grainy ID cards.
                blue = np.asarray(original)[:, :, 2]
                header = blue[
                    int(height * 0.03) : max(1, int(height * 0.40)),
                    int(width * 0.03) : int(width * 0.98),
                ]
                header = cv2.resize(header, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
                header = cv2.medianBlur(header, 3)
                header = cv2.threshold(header, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
                variants.insert(0, Image.fromarray(header))

            def add_crop(box: tuple[float, float, float, float], scale: int = 2):
                left, top, right, bottom = box
                crop = ImageOps.autocontrast(ImageOps.grayscale(original)).crop(
                    (
                        int(width * left),
                        int(height * top),
                        int(width * right),
                        int(height * bottom),
                    )
                )
                crop = crop.resize(
                    (crop.width * scale, crop.height * scale),
                    Image.Resampling.LANCZOS,
                )
                variants.append(crop)

            if document_type == DocumentType.PAN_CARD:
                # Small PAN labels can disappear when the card fills only a
                # portion of a camera photo. Retain the full-frame view and
                # add a larger, thresholded view to recover those fields.
                scale = min(1.5, 2200 / gray.width)
                upscaled = gray.resize(
                    (round(gray.width * scale), round(gray.height * scale)),
                    Image.Resampling.LANCZOS,
                )
                variants.append(ImageEnhance.Sharpness(upscaled).enhance(1.15))
                otsu = cv2.threshold(
                    np.asarray(upscaled),
                    0,
                    255,
                    cv2.THRESH_BINARY + cv2.THRESH_OTSU,
                )[1]
                variants.append(Image.fromarray(otsu))
                upscaled.close()
                # Include the top/front half used by stacked front/back scans.
                # The full-page view remains available for single-card photos.
                if height > width * 1.05:
                    add_crop((0.12, 0.04, 0.83, 0.51), scale=3)
            elif document_type == DocumentType.AADHAAR_CARD:
                # The reverse-side address block is commonly in the lower-left
                # of a stacked front/back scan. The full-page view supplies
                # identity fields; this crop supplies cleaner address lines.
                if height > width * 1.05:
                    add_crop((0.02, 0.66, 0.59, 0.86), scale=3)
            elif document_type == DocumentType.CHEQUE:
                # Preserve faint printed fields while suppressing color noise.
                threshold = ImageOps.grayscale(original).point(
                    lambda pixel: 255 if pixel > 175 else 0
                )
                variants.append(threshold)
            elif document_type == DocumentType.BANK_PASSBOOK:
                # These two panels separate bank/IFSC details from the account
                # holder block and the abbreviation legend.
                add_crop((0.00, 0.00, 0.66, 0.48), scale=2)
                # Keep the IFSC label and code together at high resolution.
                add_crop((0.00, 0.27, 0.62, 0.44), scale=4)
                add_crop((0.00, 0.46, 0.76, 0.90), scale=2)
            else:
                variants.append(ImageOps.grayscale(original))
            return variants
        finally:
            gray.close()
            original.close()

    def preprocess(self, file_path: str | Path) -> list[Image.Image]:
        path = Path(file_path)

        if not path.is_file():
            raise FileNotFoundError(f"Document not found: {path}")

        if path.suffix.lower() == ".pdf":
            pdf = pdfium.PdfDocument(str(path))
            if len(pdf) > MAX_PDF_PAGES:
                pdf.close()
                raise ValueError(f"PDF exceeds the {MAX_PDF_PAGES}-page processing limit.")
            originals = []
            for page in pdf:
                page_width, page_height = page.get_size()
                scale = min(
                    2.0,
                    (MAX_IMAGE_PIXELS / (page_width * page_height)) ** 0.5,
                )
                image = page.render(scale=scale).to_pil().convert("RGB")
                originals.append(image)
            pdf.close()
        else:
            with Image.open(path) as source:
                if source.width * source.height > MAX_IMAGE_PIXELS:
                    raise ValueError("Image exceeds the configured pixel limit.")
                # Apply EXIF orientation and create an independent image.
                originals = [ImageOps.exif_transpose(source).convert("RGB")]

        variants: list[Image.Image] = []
        for original in originals:
            variants.append(original.copy())
            grayscale = ImageOps.grayscale(original)
            enhanced = ImageOps.autocontrast(grayscale)
            width, height = enhanced.size
            if width < self.TARGET_WIDTH:
                scale = min(
                    self.TARGET_WIDTH / width,
                    self.MAX_SCALE,
                    (MAX_IMAGE_PIXELS / (width * height)) ** 0.5,
                )
                enhanced = enhanced.resize(
                    (max(1, round(width * scale)), max(1, round(height * scale))),
                    Image.Resampling.LANCZOS,
                )
            enhanced = ImageEnhance.Sharpness(enhanced).enhance(1.2)
            variants.append(enhanced.copy())
            # Adaptive thresholding keeps faint text legible when the page
            # background is uneven. Retain grayscale and color variants too.
            enhanced_array = np.asarray(enhanced)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(enhanced_array)
            adaptive = cv2.adaptiveThreshold(
                clahe,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                41,
                9,
            )
            variants.append(Image.fromarray(adaptive))
            for threshold in (160, 195):
                variants.append(
                    enhanced.point(lambda pixel, t=threshold: (255 if pixel > t else 0))
                )

        return variants

    def preprocess_passbook(self, file_path: str | Path) -> list[Image.Image]:
        """Build adaptive-threshold views of a passbook's faint account panel."""
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Document not found: {path}")
        if path.suffix.lower() == ".pdf":
            return []  # PDF pages already go through the full-page variant path.
        with Image.open(path) as source:
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise ValueError("Image exceeds the configured pixel limit.")
            original = ImageOps.exif_transpose(source).convert("RGB")

        try:
            width, height = original.size
            rgb = np.asarray(original)
            # Banking details normally occupy the lower half. Cropping the
            # left account block and right IFSC block separately avoids the
            # page's printed guide/abbreviation text overwhelming faint data.
            boxes = (
                # Account labels and values are grouped in the lower customer
                # panel. Restrict this view vertically to avoid the abbreviation
                # table and surrounding address/stamp text overwhelming OCR.
                (0.00, 0.45, 0.68, 0.83),
                # IFSC/MICR and bank branch data often sit at the fold above
                # that panel. A separate crop keeps this high-value line away
                # from both the abbreviation legend and customer details.
                # Include the printed "Br:"/branch label immediately above
                # the IFSC row; tighter crops can retain the code but clip
                # the label needed to interpret a noisy OCR token safely.
                (0.02, 0.14, 0.62, 0.44),
                (0.00, 0.40, 0.68, 0.98),
                (0.00, 0.44, 0.68, 0.98),
                (0.32, 0.40, 1.00, 0.98),
                (0.00, 0.40, 1.00, 0.98),
            )
            variants: list[Image.Image] = []
            for left, top, right, bottom in boxes:
                crop = rgb[
                    round(height * top) : round(height * bottom),
                    round(width * left) : round(width * right),
                ]
                gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
                new_width = 2200 if right - left < 0.70 else 1800
                scale = new_width / gray.shape[1]
                if gray.shape[0] * scale > MAX_IMAGE_PIXELS**0.5:
                    scale = MAX_IMAGE_PIXELS**0.5 / gray.shape[0]
                resized = cv2.resize(
                    gray,
                    (round(gray.shape[1] * scale), round(gray.shape[0] * scale)),
                    interpolation=cv2.INTER_CUBIC,
                )
                contrast = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(resized)
                adaptive = cv2.adaptiveThreshold(
                    contrast,
                    255,
                    cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                    cv2.THRESH_BINARY,
                    41,
                    9,
                )
                # Keep both contrast-preserved and binarized evidence: digit
                # strokes often disappear in only one of these views.
                variants.append(Image.fromarray(contrast))
                variants.append(Image.fromarray(adaptive))
            return variants
        finally:
            original.close()
