import csv
import os
import asyncio
import aiohttp
from typing import List, Dict, Any, Tuple, Optional
from io import StringIO, BytesIO
import logging
from urllib.parse import urlparse
import numpy as np
import cv2
from PIL import Image
import base64

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = [
    "First_Name",
    "Last_Name",
    "Title",
    "Registration_Confirmation_Number",
    "Image_URL"
]

class CSVProcessor:
    def __init__(self, face_recognizer=None, external_session=False):
        self.session = None
        self.face_recognizer = face_recognizer
        self.external_session = external_session

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session and not self.external_session:
            await self.session.close()

    def validate_csv_headers(self, headers: List[str]) -> Tuple[bool, List[str]]:
        """
        Validate that CSV contains all required columns.
        Returns (is_valid, missing_columns)
        """
        missing_columns = [col for col in REQUIRED_COLUMNS if col not in headers]
        return len(missing_columns) == 0, missing_columns

    def parse_csv_content(self, csv_content: str) -> Tuple[List[Dict[str, Any]], str]:
        """
        Parse CSV content and validate structure.
        Returns (rows, error_message)
        """
        try:
            # Remove BOM if present
            if csv_content.startswith('\ufeff'):
                csv_content = csv_content[1:]

            csv_file = StringIO(csv_content)
            reader = csv.DictReader(csv_file)

            if not reader.fieldnames:
                return [], "CSV file is empty or invalid"

            # Clean fieldnames to remove BOM and extra whitespace
            cleaned_fieldnames = []
            for field in reader.fieldnames:
                # Remove BOM character if present
                field = field.replace('\ufeff', '')
                # Strip whitespace
                field = field.strip()
                cleaned_fieldnames.append(field)

            # Update reader fieldnames
            reader.fieldnames = cleaned_fieldnames

            # Validate headers
            is_valid, missing_cols = self.validate_csv_headers(cleaned_fieldnames)
            if not is_valid:
                return [], f"Missing required columns: {', '.join(missing_cols)}"

            rows = []
            for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is row 1)
                # Create a cleaned row dict with stripped keys
                cleaned_row = {}
                for key, value in row.items():
                    if key:
                        # Clean the key (remove BOM and whitespace)
                        clean_key = key.replace('\ufeff', '').strip()
                        cleaned_row[clean_key] = value if value else ""

                # Check required fields are not empty
                missing_data = []
                for col in REQUIRED_COLUMNS:
                    if not cleaned_row.get(col, "").strip():
                        # Allow empty Image_URL
                        if col != "Image_URL":
                            missing_data.append(col)

                if missing_data:
                    logger.warning(f"Row {row_num}: Missing data for {', '.join(missing_data)}, skipping")
                    continue

                rows.append({
                    "first_name": cleaned_row["First_Name"].strip(),
                    "last_name": cleaned_row["Last_Name"].strip(),
                    "full_name": f"{cleaned_row['First_Name'].strip()} {cleaned_row['Last_Name'].strip()}",
                    "title": cleaned_row["Title"].strip(),
                    "registration_number": cleaned_row["Registration_Confirmation_Number"].strip(),
                    "image_url": cleaned_row["Image_URL"].strip() if cleaned_row.get("Image_URL") else None,
                    "row_number": row_num
                })

            return rows, ""

        except Exception as e:
            logger.error(f"Error parsing CSV: {str(e)}")
            return [], f"Error parsing CSV: {str(e)}"

    def crop_face_from_image(self, image_data: bytes) -> Optional[bytes]:
        """
        Detect and crop the face from an image using ML models.
        Returns cropped face image data or original if no face detected.
        """
        try:
            if not self.face_recognizer:
                return image_data

            # Convert bytes to PIL Image
            image = Image.open(BytesIO(image_data))

            # Convert to OpenCV format
            image_cv = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

            # Detect faces using the face recognizer
            _, face_detections = self.face_recognizer.recognize_face(image_cv, "temp.png")

            if face_detections and len(face_detections) > 0:
                # Get the first (largest) face
                face = face_detections[0]
                x, y, w, h = face.bbox  # bbox is a tuple attribute, not a dict key

                # Add padding around the face (20% on each side)
                padding = 0.2
                x_pad = int(w * padding)
                y_pad = int(h * padding)

                # Calculate new boundaries with padding
                x1 = max(0, x - x_pad)
                y1 = max(0, y - y_pad)
                x2 = min(image_cv.shape[1], x + w + x_pad)
                y2 = min(image_cv.shape[0], y + h + y_pad)

                # Crop the face with padding
                cropped_face = image_cv[y1:y2, x1:x2]

                # Convert back to bytes
                _, buffer = cv2.imencode('.jpg', cropped_face)
                return buffer.tobytes()

            # Return original if no face detected
            return image_data

        except Exception as e:
            logger.warning(f"Error cropping face: {str(e)}")
            return image_data

    async def download_image(self, url: str) -> Tuple[bytes, str]:
        """
        Download image from URL and optionally crop face.
        Returns (image_data, error_message)
        """
        if not url:
            return None, "No image URL provided"

        try:
            # Basic URL validation
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                return None, f"Invalid URL: {url}"

            async with self.session.get(url, timeout=30) as response:
                if response.status != 200:
                    return None, f"Failed to download image: HTTP {response.status}"

                # Check content type
                content_type = response.headers.get('Content-Type', '')
                if not content_type.startswith('image/'):
                    return None, f"URL does not point to an image (Content-Type: {content_type})"

                # Read image data
                image_data = await response.read()

                # Basic size validation (min 1KB, max 10MB)
                if len(image_data) < 1024:
                    return None, "Image too small (< 1KB)"
                if len(image_data) > 10 * 1024 * 1024:
                    return None, "Image too large (> 10MB)"

                # Crop face if face recognizer is available
                if self.face_recognizer:
                    image_data = self.crop_face_from_image(image_data)

                return image_data, ""

        except asyncio.TimeoutError:
            return None, "Image download timed out"
        except Exception as e:
            logger.error(f"Error downloading image from {url}: {str(e)}")
            return None, f"Error downloading image: {str(e)}"

    async def process_csv_for_registration(self, csv_content: str) -> Dict[str, Any]:
        """
        Process CSV content for bulk registration.
        Returns results dictionary with processed rows and statistics.
        """
        try:
            print(f"DEBUG: Starting CSV processing, content length: {len(csv_content)}")

            # Parse CSV
            rows, error = self.parse_csv_content(csv_content)
            if error:
                print(f"DEBUG: CSV parsing error: {error}")
                return {
                    "success": False,
                    "error": error,
                    "total_rows": 0,
                    "processed_rows": []
                }

            print(f"DEBUG: Successfully parsed {len(rows)} rows")
        except Exception as e:
            print(f"DEBUG: Exception in process_csv_for_registration: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": f"Error in CSV processing: {str(e)}",
                "total_rows": 0,
                "processed_rows": []
            }

        # Process each row
        processed_rows = []
        for row in rows:
            row_result = {
                "row_number": row["row_number"],
                "full_name": row["full_name"],
                "title": row["title"],
                "registration_number": row["registration_number"],
                "image_downloaded": False,
                "image_data": None,
                "error": None
            }

            # Download image if URL provided
            if row["image_url"]:
                print(f"DEBUG: Attempting to download image for {row['full_name']}")
                try:
                    image_data, error = await self.download_image(row["image_url"])
                    if error:
                        print(f"DEBUG: Image download error: {error}")
                        row_result["error"] = error
                        logger.warning(f"Row {row['row_number']}: Failed to download image for {row['full_name']}: {error}")
                    else:
                        print(f"DEBUG: Successfully downloaded image for {row['full_name']}")
                        row_result["image_downloaded"] = True
                        row_result["image_data"] = image_data
                except Exception as e:
                    print(f"DEBUG: Exception during image download: {e}")
                    row_result["error"] = str(e)
            else:
                print(f"DEBUG: No image URL for {row['full_name']}")
                logger.info(f"Row {row['row_number']}: No image URL for {row['full_name']}")

            processed_rows.append(row_result)

        return {
            "success": True,
            "total_rows": len(rows),
            "processed_rows": processed_rows,
            "required_columns": REQUIRED_COLUMNS
        }

async def process_csv(csv_content: str, face_recognizer=None) -> Dict[str, Any]:
    """
    Convenience function to process CSV content.
    """
    async with CSVProcessor(face_recognizer) as processor:
        return await processor.process_csv_for_registration(csv_content)