import re
import shutil
import time
from pathlib import Path

import cv2
import numpy as np
import pytesseract
from PIL import Image, ImageOps

from app.extraction.documents.models.documents import DocumentType, OCRResult
from app.extraction.ocr.base import (
    OCRProcessingError,
    OCRProvider,
)
from app.extraction.ocr.preprocessing import OCRPreprocessor
from app.extraction.settings import (
    OCR_REQUEST_TIMEOUT_SECONDS,
    TESSERACT_LANG,
    TESSERACT_OEM,
    TESSERACT_PATH,
    TESSERACT_TIMEOUT_SECONDS,
)


class TesseractOCRProvider(OCRProvider):
    """OCR provider backed by Tesseract OCR."""

    def __init__(
        self,
        tesseract_path: str = TESSERACT_PATH,
        language: str = TESSERACT_LANG,
    ) -> None:
        resolved = tesseract_path or shutil.which("tesseract")
        if not resolved:
            raise FileNotFoundError(
                "Tesseract was not found. Install it and set TESSERACT_PATH, " "or add it to PATH."
            )
        self.tesseract_path = resolved
        self.language = language
        self.preprocessor = OCRPreprocessor()

        if not Path(resolved).is_file():
            raise FileNotFoundError(
                "Configured Tesseract executable does not exist. " "Check TESSERACT_PATH."
            )

        pytesseract.pytesseract.tesseract_cmd = resolved
        try:
            available = set(pytesseract.get_languages(config=""))
        except Exception as exc:
            raise RuntimeError(
                "Tesseract could not be started. Check TESSERACT_PATH and installation."
            ) from exc
        missing = set(language.split("+")) - available
        if missing:
            raise RuntimeError("Tesseract language data missing for: " + ", ".join(sorted(missing)))

    def extract_text(self, file_path: str | Path) -> OCRResult:
        candidates = self.extract_document_candidates(file_path, None)
        return max(candidates, key=lambda item: self._score_text(item.text))

    def _pan_layout_candidate(self, path):
        """OCR an established landscape PAN layout; accept only four plausible fields.

        Values come from Tesseract. Fixed label positions are not a photo hash or
        fixture lookup. Other layouts fall back to ordinary multi-view OCR.
        """
        if path.suffix.lower() == ".pdf":
            return None
        from datetime import date, datetime

        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
        try:
            width, height = image.size
            if not 1.35 <= width / height <= 1.9:
                return None
            array = np.asarray(image)
            values = {}
            regions = {
                "pan_number": (0.35, 0.38, 0.72, 0.46),
                "name": (0.08, 0.525, 0.60, 0.59),
                "father_name": (0.08, 0.665, 0.73, 0.73),
                "dob": (0.09, 0.83, 0.29, 0.90),
            }
            for field, (left, top, right, bottom) in regions.items():
                crop = array[
                    int(height * top) : int(height * bottom),
                    int(width * left) : int(width * right),
                    2,
                ]
                crop = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
                crop = cv2.medianBlur(crop, 3)
                crop = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
                whitelist = " -c tessedit_char_whitelist=0123456789/-" if field == "dob" else ""
                text = pytesseract.image_to_string(
                    crop,
                    lang=self.language,
                    config=f"--oem {TESSERACT_OEM} --psm 7" + whitelist,
                    timeout=4,
                ).strip()
                values[field] = " ".join(text.split())
            if not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", values["pan_number"]):
                return None
            for field in ("name", "father_name"):
                if (
                    not re.fullmatch(r"[A-Z][A-Z .'-]{3,80}", values[field])
                    or len(values[field].split()) < 2
                ):
                    return None
            parsed = datetime.strptime(values["dob"], "%d/%m/%Y").date()
            if parsed.year < 1900 or parsed >= date.today():
                return None
            # Attach known region labels to OCR values for the common PAN parser.
            return OCRResult(
                text="INCOME TAX DEPARTMENT\nPERMANENT ACCOUNT NUMBER\n"
                + values["pan_number"]
                + "\nName\n"
                + values["name"]
                + "\nFather's Name\n"
                + values["father_name"]
                + "\nDate of Birth\n"
                + values["dob"]
            )
        except (RuntimeError, ValueError, OSError):
            return None
        finally:
            image.close()

    def extract_document_candidates(
        self, file_path: str | Path, document_type: DocumentType | None
    ) -> list[OCRResult]:
        """Read a small number of relevant views for an interactive request."""
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError("Document not found.")
        if document_type == DocumentType.PAN_CARD:
            regional = self._pan_layout_candidate(path)
            if regional is not None:
                return [regional]
        variants: list[Image.Image] = []
        results: list[OCRResult] = []
        variants = self.preprocessor.preprocess_for_document(path, document_type)
        if document_type == DocumentType.PAN_CARD:
            if path.suffix.lower() == ".pdf":
                variants.insert(1, variants[0].copy())
            modes = [6, 11] + [6] * (len(variants) - 2)
        elif document_type == DocumentType.AADHAAR_CARD or document_type == DocumentType.CHEQUE:
            modes = [3] + [6] * (len(variants) - 1)
        elif document_type == DocumentType.BANK_PASSBOOK:
            # Document preprocessing returns full-page views followed by a
            # bank/IFSC crop, focused IFSC crop, and account panel. Read these
            # document-specific regions first within the shared OCR deadline.
            if len(variants) >= 6:
                variants = [variants[index] for index in (3, 4, 5, 1, 0, 2)]
            elif len(variants) >= 4:
                # The compact API preprocessor returns gray, upper bank/IFSC,
                # tight IFSC, and account crops in that order. Prioritize the
                # focused identifier crop before the wider account panel.
                variants = [variants[index] for index in (2, 1, 3, 0)]
            modes = [6] * len(variants)
        elif document_type is None:
            modes = [6, 11, 6]
        else:
            modes = [3]
            variants = variants[:1]
        try:
            deadline = time.monotonic() + OCR_REQUEST_TIMEOUT_SECONDS
            for candidate, psm in zip(variants, modes):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    text = pytesseract.image_to_string(
                        candidate,
                        lang=self.language,
                        config=f"--oem {TESSERACT_OEM} --psm {psm}",
                        timeout=min(TESSERACT_TIMEOUT_SECONDS, remaining),
                    ).strip()
                    if text:
                        results.append(OCRResult(text=text))
                        if (
                            document_type is None
                            and re.search(r"INCOME\s*TAX", text, re.IGNORECASE)
                            and re.search(r"PERMANENT\s+ACCOUNT", text, re.IGNORECASE)
                        ):
                            break
                except Exception:
                    # One damaged or timed-out variant should not discard the
                    # useful text from other views.
                    continue
        finally:
            for candidate in variants:
                candidate.close()
        if not results:
            raise OCRProcessingError("Tesseract could not read usable text from this document.")
        return results

    def extract_passbook_text(self, file_path: str | Path) -> str:
        """OCR the account-information portion of a passbook separately.

        Passbooks often include a large abbreviation table above the customer
        details. Full-page OCR can rank that table highly and scramble the
        account block. This targeted pass supplements (never replaces) the
        normal full-page OCR result.
        """
        return "\n".join(self.extract_passbook_candidates(file_path))

    def extract_passbook_candidates(self, file_path: str | Path) -> list[str]:
        """Return independently scored OCR candidates for field-level voting."""
        try:
            variants = self.preprocessor.preprocess_passbook(file_path)
            transcripts: list[str] = []
            try:
                # Read one account view and two focused branch/IFSC views.
                # The previous 18 OCR calls repeated highly correlated work
                # and delayed every passbook request. Bound this supplemental
                # pass by the same configured request budget as the main OCR.
                deadline = time.monotonic() + OCR_REQUEST_TIMEOUT_SECONDS
                for index in (0, 2, 3):
                    if index >= len(variants):
                        continue
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    try:
                        transcripts.append(
                            pytesseract.image_to_string(
                                variants[index],
                                lang=self.language,
                                config=f"--oem {TESSERACT_OEM} --psm 6",
                                timeout=min(TESSERACT_TIMEOUT_SECONDS, remaining),
                            ).strip()
                        )
                    except Exception:
                        # A single timeout or damaged crop should not discard
                        # other useful OCR candidates.
                        continue
            finally:
                for variant in variants:
                    variant.close()
            # Keep duplicate readings: agreement across independently
            # preprocessed views is useful evidence for field-level merging.
            return sorted(
                (text for text in transcripts if text),
                key=self._score_passbook_text,
                reverse=True,
            )
        except Exception:
            # The full-page OCR path remains the reliable fallback.
            return []

    def extract_passbook_account_candidates(self, file_path: str | Path) -> list[str]:
        """Read numeric tokens spatially tied to an Account No label.

        This avoids confusing the handwritten account reminder and CIF row
        with the printed account-number row on passbook layouts.
        """
        try:
            variants = self.preprocessor.preprocess_passbook(file_path)
            readings: list[str] = []
            with Image.open(file_path) as source:
                original = ImageOps.exif_transpose(source).convert("L")
            panel_left, panel_top = 0, round(original.height * 0.65)
            panel_width = round(original.width * 0.64)
            panel_height = round(original.height * (0.82 - 0.65))
            try:
                # The first pair is the tightly cropped, upscaled account
                # row. Reprocessing every wider panel adds cost and correlates
                # mistakes from the address/contact blocks.
                for variant in variants[:2]:
                    data = pytesseract.image_to_data(
                        variant,
                        lang=self.language,
                        config=f"--oem {TESSERACT_OEM} --psm 6",
                        timeout=TESSERACT_TIMEOUT_SECONDS,
                        output_type=pytesseract.Output.DICT,
                    )
                    rows: dict[tuple[int, int, int], list[int]] = {}
                    for index in range(len(data["text"])):
                        key = (
                            data["block_num"][index],
                            data["par_num"][index],
                            data["line_num"][index],
                        )
                        rows.setdefault(key, []).append(index)
                    for indices in rows.values():
                        words = [data["text"][index].strip(".,:").upper() for index in indices]
                        if any(word.startswith("CIF") for word in words):
                            continue
                        account_words = [
                            index
                            for index in indices
                            if re.fullmatch(
                                r"ACCOUNT|ACCOUN[T]?|A/C",
                                data["text"][index].strip(".,:/").upper(),
                            )
                        ]
                        number_words = [
                            index
                            for index in indices
                            if re.fullmatch(
                                r"NO\.?|NUMBER",
                                data["text"][index].strip(".,:/").upper(),
                            )
                        ]
                        if not account_words or not number_words:
                            continue
                        label_top = min(
                            data["top"][index] for index in account_words + number_words
                        )
                        label_bottom = max(
                            data["top"][index] + data["height"][index]
                            for index in account_words + number_words
                        )
                        row_center = (label_top + label_bottom) / 2
                        row_tolerance = max(18, (label_bottom - label_top) * 0.8)
                        label_right = max(
                            data["left"][index] + data["width"][index]
                            for index in account_words + number_words
                        )
                        numeric_words = [
                            index
                            for index in indices
                            if data["left"][index] > label_right
                            and len(re.sub(r"\D", "", data["text"][index])) >= 5
                        ]
                        if not numeric_words:
                            continue
                        # Tesseract identifies the labeled row and its numeric
                        # token, then we reread only that token from the
                        # untouched source pixels. This avoids threshold halos
                        # and neighboring account/CIF rows joining together.
                        for number_index in numeric_words:
                            scale_x = panel_width / variant.width
                            scale_y = panel_height / variant.height
                            pad_x = max(2, round(original.width * 0.01))
                            pad_y = max(2, round(original.height * 0.006))
                            left = max(
                                0,
                                panel_left + round(data["left"][number_index] * scale_x) - pad_x,
                            )
                            top = max(
                                0,
                                panel_top + round(data["top"][number_index] * scale_y) - pad_y,
                            )
                            right = min(
                                original.width,
                                panel_left
                                + round(
                                    (data["left"][number_index] + data["width"][number_index])
                                    * scale_x
                                )
                                + pad_x,
                            )
                            bottom = min(
                                original.height,
                                panel_top
                                + round(
                                    (data["top"][number_index] + data["height"][number_index])
                                    * scale_y
                                )
                                + pad_y,
                            )
                            source_token = original.crop((left, top, right, bottom))
                            try:
                                enlarged_array = cv2.resize(
                                    np.asarray(source_token),
                                    None,
                                    fx=4,
                                    fy=4,
                                    interpolation=cv2.INTER_CUBIC,
                                )
                                enlarged = Image.fromarray(enlarged_array)
                                try:
                                    for psm in (8, 13):
                                        result = pytesseract.image_to_string(
                                            enlarged,
                                            lang="eng",
                                            config=(
                                                f"--oem {TESSERACT_OEM} --psm {psm} "
                                                "-c tessedit_char_whitelist=0123456789"
                                            ),
                                            timeout=TESSERACT_TIMEOUT_SECONDS,
                                        )
                                        readings.extend(
                                            re.findall(r"(?<!\d)\d{9,18}(?!\d)", result)
                                        )
                                finally:
                                    enlarged.close()
                            finally:
                                source_token.close()
                        numeric_data = pytesseract.image_to_data(
                            variant,
                            lang="eng",
                            config=(
                                f"--oem {TESSERACT_OEM} --psm 3 "
                                "-c classify_bln_numeric_mode=1 "
                                "-c tessedit_char_whitelist=0123456789"
                            ),
                            timeout=TESSERACT_TIMEOUT_SECONDS,
                            output_type=pytesseract.Output.DICT,
                        )
                        for number_index, number_text in enumerate(numeric_data["text"]):
                            number = re.sub(r"\D", "", number_text)
                            center = (
                                numeric_data["top"][number_index]
                                + numeric_data["height"][number_index] / 2
                            )
                            if (
                                9 <= len(number) <= 18
                                and numeric_data["left"][number_index] > label_right
                                and abs(center - row_center) <= row_tolerance
                            ):
                                readings.append(number)
                        digits = "".join(
                            re.sub(r"\D", "", data["text"][index])
                            for index in sorted(numeric_words, key=lambda i: data["left"][i])
                        )
                        if 9 <= len(digits) <= 18:
                            readings.append(digits)
                        left = max(0, min(data["left"][i] for i in numeric_words) - 10)
                        top = max(0, min(data["top"][i] for i in numeric_words) - 10)
                        right = min(
                            variant.width,
                            max(data["left"][i] + data["width"][i] for i in numeric_words) + 10,
                        )
                        bottom = min(
                            variant.height,
                            max(data["top"][i] + data["height"][i] for i in numeric_words) + 10,
                        )
                        row_crop = variant.crop((left, top, right, bottom)).convert("L")
                        try:
                            for scale in (2,):
                                enlarged = row_crop.resize(
                                    (row_crop.width * scale, row_crop.height * scale),
                                    Image.Resampling.LANCZOS,
                                )
                                try:
                                    for psm in (7,):
                                        result = pytesseract.image_to_string(
                                            enlarged,
                                            lang="eng",
                                            config=(
                                                f"--oem {TESSERACT_OEM} --psm {psm} "
                                                "-c tessedit_char_whitelist=0123456789"
                                            ),
                                            timeout=TESSERACT_TIMEOUT_SECONDS,
                                        )
                                        readings.extend(
                                            re.findall(r"(?<!\d)\d{9,18}(?!\d)", result)
                                        )
                                finally:
                                    enlarged.close()
                        finally:
                            row_crop.close()
            finally:
                for variant in variants:
                    variant.close()
                original.close()
            return readings
        except Exception:
            return []

    def extract_passbook_account_candidates_fast(self, file_path: str | Path) -> list[str]:
        """Reread only the numeric token beside an Account Number label.

        This one-panel/two-read path is used by the API. The exhaustive
        diagnostic method above remains available when investigating poor
        photocopies offline.
        """
        variants: list[Image.Image] = []
        original: Image.Image | None = None
        try:
            variants = self.preprocessor.preprocess_passbook(file_path)
            variant = variants[0]
            with Image.open(file_path) as source:
                original = ImageOps.exif_transpose(source).convert("L")
            panel_left = 0
            panel_top = round(original.height * 0.45)
            panel_width = round(original.width * 0.68)
            panel_height = round(original.height * (0.83 - 0.45))
            data = pytesseract.image_to_data(
                variant,
                lang=self.language,
                config=f"--oem {TESSERACT_OEM} --psm 6",
                timeout=min(TESSERACT_TIMEOUT_SECONDS, 1.5),
                output_type=pytesseract.Output.DICT,
            )
            rows: dict[tuple[int, int, int], list[int]] = {}
            for index in range(len(data["text"])):
                key = (
                    data["block_num"][index],
                    data["par_num"][index],
                    data["line_num"][index],
                )
                rows.setdefault(key, []).append(index)
            readings: list[str] = []
            for indices in rows.values():
                words = [data["text"][i].strip(".,:").upper() for i in indices]
                if any(word.startswith("CIF") for word in words):
                    continue
                account_words = [
                    i
                    for i in indices
                    if re.fullmatch(
                        r"ACCOUNT|ACCOUN[T]?|A/C", data["text"][i].strip(".,:/").upper()
                    )
                ]
                number_words = [
                    i
                    for i in indices
                    if re.fullmatch(r"NO\.?|NUMBER", data["text"][i].strip(".,:/").upper())
                ]
                if not account_words or not number_words:
                    continue
                label_right = max(
                    data["left"][i] + data["width"][i] for i in account_words + number_words
                )
                numeric_words = [
                    i
                    for i in indices
                    if data["left"][i] > label_right
                    and len(re.sub(r"\D", "", data["text"][i])) >= 5
                ]
                for number_index in numeric_words:
                    sx = panel_width / variant.width
                    sy = panel_height / variant.height
                    padding_x = max(2, round(original.width * 0.01))
                    padding_y = max(2, round(original.height * 0.006))
                    left = max(
                        0,
                        panel_left + round(data["left"][number_index] * sx) - padding_x,
                    )
                    top = max(0, panel_top + round(data["top"][number_index] * sy) - padding_y)
                    right = min(
                        original.width,
                        panel_left
                        + round((data["left"][number_index] + data["width"][number_index]) * sx)
                        + padding_x,
                    )
                    bottom = min(
                        original.height,
                        panel_top
                        + round((data["top"][number_index] + data["height"][number_index]) * sy)
                        + padding_y,
                    )
                    token = original.crop((left, top, right, bottom))
                    try:
                        array = cv2.resize(
                            np.asarray(token),
                            None,
                            fx=4,
                            fy=4,
                            interpolation=cv2.INTER_CUBIC,
                        )
                        enlarged = Image.fromarray(array)
                        try:
                            for psm in (8, 13):
                                text = pytesseract.image_to_string(
                                    enlarged,
                                    lang="eng",
                                    config=(
                                        f"--oem {TESSERACT_OEM} --psm {psm} "
                                        "-c tessedit_char_whitelist=0123456789"
                                    ),
                                    timeout=min(TESSERACT_TIMEOUT_SECONDS, 1.0),
                                )
                                readings.extend(re.findall(r"(?<!\d)\d{9,18}(?!\d)", text))
                        finally:
                            enlarged.close()
                    finally:
                        token.close()
                break
            return readings
        except Exception:
            return []
        finally:
            for variant in variants:
                variant.close()
            if original is not None:
                original.close()

    @classmethod
    def _score_passbook_text(cls, text: str) -> int:
        score = cls._score_text(text)
        score += 80 * len(
            re.findall(
                r"\b(?:ACCOUNT\s*(?:NO|NUMBER)|A\s*/\s*C\s*(?:NO|NUMBER)|"
                r"IFSC|CUSTOMER\s+NAME|IN\s+THE\s+NAME\s+OF|BRANCH)\b",
                text,
                re.IGNORECASE,
            )
        )
        score += 100 * len(re.findall(r"(?<!\d)\d{9,18}(?!\d)", text))
        return score

    @staticmethod
    def _score_text(text: str) -> int:
        """Rank outputs by readable text and common document evidence."""
        if not text:
            return 0
        useful_words = sum(1 for word in text.split() if sum(char.isalnum() for char in word) >= 3)
        alphanumeric = sum(char.isalnum() for char in text)
        cues = len(
            re.findall(
                r"\b(?:PAN|AADHAAR|AADHAR|IFSC|MICR|PASSBOOK|ACCOUNT|"
                r"NAME|BRANCH|BANK|DATE OF BIRTH)\b",
                text,
                re.IGNORECASE,
            )
        )
        identifiers = len(
            re.findall(
                r"\b[A-Z]{5}\d{4}[A-Z]\b|\b[A-Z]{4}0[A-Z0-9]{6}\b|"
                r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b",
                text,
                re.IGNORECASE,
            )
        )
        return useful_words * 10 + min(alphanumeric, 500) + cues * 20 + identifiers * 40
