import csv
import os
import asyncio
import aiohttp
from typing import List, Dict, Any, Tuple, Optional, Callable
from io import StringIO, BytesIO
import logging
from urllib.parse import urlparse
import numpy as np
import cv2
from PIL import Image, ImageOps
import json
import uuid

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = [
    "First_Name",
    "Last_Name",
    "Title",
    "Registration_Confirmation_Number",
    "Image_URL"
]

# Optional columns for multi-photo support
OPTIONAL_COLUMNS = [
    "Image_URL_2",
    "Image_URL_3",
    "Image_URL_4",
    "Image_URL_5"
]

class CSVProcessor:
    def __init__(self, face_recognizer=None, database=None, external_session=False):
        self.session = None
        self.face_recognizer = face_recognizer
        self.database = database
        self.external_session = external_session

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

                # Collect all image URLs (primary + optional additional photos)
                image_urls = []
                if cleaned_row.get("Image_URL", "").strip():
                    image_urls.append(cleaned_row["Image_URL"].strip())

                # Check for additional image URLs (for ensemble voting)
                for optional_col in OPTIONAL_COLUMNS:
                    if cleaned_row.get(optional_col, "").strip():
                        image_urls.append(cleaned_row[optional_col].strip())

                rows.append({
                    "first_name": cleaned_row["First_Name"].strip(),
                    "last_name": cleaned_row["Last_Name"].strip(),
                    "full_name": f"{cleaned_row['First_Name'].strip()} {cleaned_row['Last_Name'].strip()}",
                    "title": cleaned_row["Title"].strip(),
                    "registration_number": cleaned_row["Registration_Confirmation_Number"].strip(),
                    "image_url": image_urls[0] if image_urls else None,  # Primary image (backward compat)
                    "image_urls": image_urls,  # All images for multi-photo support
                    "row_number": row_num
                })

            return rows, ""

        except Exception as e:
            logger.error(f"Error parsing CSV: {str(e)}")
            return [], f"Error parsing CSV: {str(e)}"

    def crop_face_from_image(self, image_data: bytes) -> Tuple[Optional[bytes], bool, str]:
        """
        Detect and crop the face from an image using ML models.
        Returns (image_data, face_detected, error_message)
        """
        try:
            if not self.face_recognizer:
                return image_data, True, ""  # Assume success if no recognizer

            # Convert bytes to PIL Image
            image = Image.open(BytesIO(image_data))

            # Fix EXIF orientation (this handles sideways/rotated images)
            image = ImageOps.exif_transpose(image)

            # Convert to OpenCV format
            image_cv = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

            # Detect faces using the registration-specific face recognizer
            _, face_detections = self.face_recognizer.recognize_face_for_registration(image_cv, "temp.png")

            if not face_detections or len(face_detections) == 0:
                # No face detected
                return None, False, "No face detected in image"

            if len(face_detections) > 1:
                # Multiple faces detected - reject
                return None, False, f"Multiple faces detected ({len(face_detections)} faces). Please use a photo with only one person."

            # Exactly one face - proceed with cropping
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
            return buffer.tobytes(), True, ""

        except Exception as e:
            error_msg = f"Error cropping face: {str(e)}"
            logger.warning(error_msg)
            return None, False, error_msg

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
                    cropped_image, face_detected, error = self.crop_face_from_image(image_data)
                    if not face_detected:
                        return None, error
                    image_data = cropped_image

                return image_data, ""

        except asyncio.TimeoutError:
            return None, "Image download timed out"
        except Exception as e:
            logger.error(f"Error downloading image from {url}: {str(e)}")
            return None, f"Error downloading image: {str(e)}"

async def process_csv_with_progress_streaming(
    csv_content: str,
    face_recognizer,
    database,
    generate_thumbnail_callback: Callable[[str], None]
):
    """
    Process CSV with progress callbacks via Server-Sent Events.

    Args:
        csv_content: CSV file content as string
        face_recognizer: Face recognition instance
        database: Database manager instance
        generate_thumbnail_callback: Function to generate thumbnails (person_id) -> None

    Yields:
        SSE formatted progress events
    """
    # Create session and processor
    session = aiohttp.ClientSession()
    processor = CSVProcessor(face_recognizer, database, external_session=True)
    processor.session = session

    try:
        # Parse CSV
        yield f"event: progress\ndata: {json.dumps({'stage': 'parsing', 'message': 'Parsing CSV file...'})}\n\n"

        rows, error = processor.parse_csv_content(csv_content)
        if error:
            yield f"event: error\ndata: {json.dumps({'error': error})}\n\n"
            return

        yield f"event: progress\ndata: {json.dumps({'stage': 'processing', 'message': f'Processing {len(rows)} users...'})}\n\n"

        # Phase 1: Pre-filter and prepare for concurrent download
        successful_registrations = []
        failed_registrations = []
        skipped_no_image = []
        persons_for_batch = []
        person_metadata = {}

        # Pre-filter rows
        rows_to_download = []
        for row in rows:
            # Check if registration ID already exists
            if database.check_registration_exists(row["registration_number"]):
                failed_registrations.append({
                    'row_number': row['row_number'],
                    'name': row['full_name'],
                    'title': row['title'],
                    'registration_number': row['registration_number'],
                    'error': f'Registration ID "{row["registration_number"]}" already exists in database'
                })
                continue

            # Check if image URL provided
            if not row["image_url"]:
                skipped_no_image.append({
                    'row_number': row['row_number'],
                    'name': row['full_name'],
                    'title': row['title'],
                    'registration_number': row['registration_number'],
                    'error': 'No image URL provided'
                })
                continue

            rows_to_download.append(row)

        # Phase 2: Download all images concurrently (supports multiple photos per person!)
        if rows_to_download:
            # Count total images
            total_images = sum(len(row.get("image_urls", [row["image_url"]])) for row in rows_to_download)
            num_people = len(rows_to_download)
            progress_msg = {
                'stage': 'downloading',
                'message': f'Downloading {total_images} images for {num_people} people...',
                'percentage': 25
            }
            yield f"event: progress\ndata: {json.dumps(progress_msg)}\n\n"

            # Create download tasks for ALL images (including multiple per person)
            download_coroutines = []
            task_metadata = []

            for row in rows_to_download:
                image_urls = row.get("image_urls", [row["image_url"]])
                for photo_num, image_url in enumerate(image_urls, start=1):
                    download_coroutines.append(processor.download_image(image_url))
                    task_metadata.append((row['registration_number'], row['row_number'], row['full_name'], row['title'], photo_num))

            # Execute all downloads with progress tracking
            all_tasks = [asyncio.create_task(coro) for coro in download_coroutines]
            pending = set(all_tasks)

            # Monitor progress while tasks are running
            completed_count = 0
            last_progress_update = 0

            while pending:
                # Wait for at least one task to complete
                done, pending = await asyncio.wait(
                    pending,
                    return_when=asyncio.FIRST_COMPLETED
                )

                completed_count += len(done)

                # Update progress every 10% or at completion
                progress_percent = int((completed_count / total_images) * 100)
                if progress_percent >= last_progress_update + 10 or completed_count == total_images:
                    last_progress_update = progress_percent
                    progress_msg = {
                        'stage': 'downloading',
                        'message': f'Downloaded {completed_count}/{total_images} images ({progress_percent}%)...',
                        'percentage': 25 + int(progress_percent * 0.25)  # Map 0-100% to 25-50%
                    }
                    yield f"event: progress\ndata: {json.dumps(progress_msg)}\n\n"

            # All tasks are done, collect results in original order
            download_results = []
            for task in all_tasks:
                try:
                    download_results.append(task.result())
                except Exception as e:
                    download_results.append(e)

            # Phase 3: Process downloaded images (group by person)
            person_photos = {}  # registration_number -> list of (photo_num, image_data)
            person_info = {}    # registration_number -> (row_number, full_name, title)
            person_errors = {}  # registration_number -> list of error messages

            # Process results in original order
            for (reg_num, row_num, full_name, title, photo_num), download_result in zip(task_metadata, download_results):
                # Store person info
                if reg_num not in person_info:
                    person_info[reg_num] = (row_num, full_name, title)
                    person_photos[reg_num] = []
                    person_errors[reg_num] = []

                # Handle download result
                if isinstance(download_result, Exception):
                    error_msg = f"Photo {photo_num} download failed: {download_result}"
                    print(f"⚠️ {error_msg} for {full_name}")
                    person_errors[reg_num].append(error_msg)
                    continue

                image_data, error = download_result
                if error:
                    error_msg = f"Photo {photo_num}: {error}"
                    print(f"⚠️ {error_msg} for {full_name}")
                    person_errors[reg_num].append(error_msg)
                    continue

                person_photos[reg_num].append((photo_num, image_data))

            # Process each person with their photos
            # IMPORTANT: Iterate over person_info (not person_photos) to catch people with ALL failed photos
            for reg_num, (row_num, full_name, title) in person_info.items():
                photos = person_photos.get(reg_num, [])

                if not photos:
                    # No successful photos for this person - use specific error messages
                    error_messages = person_errors.get(reg_num, [])
                    if error_messages:
                        # Join all unique error messages
                        error = '; '.join(error_messages)
                    else:
                        error = 'All image downloads failed'

                    failed_registrations.append({
                        'row_number': row_num,
                        'name': full_name,
                        'title': title,
                        'registration_number': reg_num,
                        'error': error
                    })
                    continue

                person_id = None
                photo_paths = []

                try:
                    # Generate unique ID
                    person_id = str(uuid.uuid4())

                    # Insert person to database
                    db_result = database.insert_into_person(person_id, full_name, title, reg_num)

                    if 'already exist' in db_result:
                        failed_registrations.append({
                            'row_number': row_num,
                            'name': full_name,
                            'title': title,
                            'registration_number': reg_num,
                            'error': 'Person already exists'
                        })
                        continue

                    # Save all photos for this person
                    os.makedirs('images', exist_ok=True)
                    photo_paths = []

                    for photo_num, image_data in photos:
                        image = Image.open(BytesIO(image_data))
                        image_cv = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

                        # Save with photo number for ensemble
                        image_path = f'images/{person_id}%{photo_num}.png'
                        cv2.imwrite(image_path, image_cv)
                        photo_paths.append(image_path)

                    # Add all photos to batch queue
                    for image_path in photo_paths:
                        persons_for_batch.append((person_id, image_path))

                    # Store metadata once per person
                    if person_id not in person_metadata:
                        person_metadata[person_id] = {
                            'row_number': row_num,
                            'name': full_name,
                            'title': title,
                            'registration_number': reg_num,
                            'photo_count': len(photo_paths)
                        }

                except Exception as e:
                    if person_id:
                        database.delete_data_from_person(person_id)
                        for path in photo_paths:
                            if os.path.exists(path):
                                os.remove(path)

                    failed_registrations.append({
                        'row_number': row_num,
                        'name': full_name,
                        'title': title,
                        'registration_number': reg_num,
                        'error': str(e)
                    })

        # Phase 4: Batch process face embeddings (optimized for pre-cropped images)
        if persons_for_batch:
            num_photos = len(persons_for_batch)
            progress_msg = {
                'stage': 'face_processing',
                'message': f'Processing faces for {num_photos} photos...',
                'percentage': 75
            }
            yield f"event: progress\ndata: {json.dumps(progress_msg)}\n\n"

            # Use optimized method for pre-cropped images (skips redundant face detection)
            batch_results = face_recognizer.add_pre_cropped_photos_to_database_batch(persons_for_batch)

            # Process batch results
            for success_item in batch_results['successful']:
                person_id = success_item['person_id']
                metadata = person_metadata[person_id]

                # Generate thumbnail
                generate_thumbnail_callback(person_id)

                successful_registrations.append({
                    'row_number': metadata['row_number'],
                    'person_id': person_id,
                    'name': metadata['name'],
                    'title': metadata['title'],
                    'registration_number': metadata['registration_number'],
                    'has_image': True
                })

            # Handle batch failures
            for fail_item in batch_results['failed']:
                person_id = fail_item['person_id']
                metadata = person_metadata[person_id]
                image_path = fail_item['image_path']

                # Rollback
                database.delete_data_from_person(person_id)
                if os.path.exists(image_path):
                    os.remove(image_path)

                failed_registrations.append({
                    'row_number': metadata['row_number'],
                    'name': metadata['name'],
                    'title': metadata['title'],
                    'registration_number': metadata['registration_number'],
                    'error': fail_item.get('error', 'Failed to add face to recognition database')
                })

        # Send final results
        final_data = {
            'success': True,
            'total_rows': len(rows),
            'successful_registrations': len(successful_registrations),
            'failed_registrations': len(failed_registrations),
            'skipped_no_image': len(skipped_no_image),
            'details': {
                'successful': successful_registrations,
                'failed': failed_registrations,
                'skipped': skipped_no_image
            }
        }
        yield f"event: complete\ndata: {json.dumps(final_data)}\n\n"

    finally:
        # Always close session
        await session.close()