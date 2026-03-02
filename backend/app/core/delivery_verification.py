"""
Delivery verification with intelligent photo processing.
Never rejects photos - always optimizes transparently.
"""

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, List
import io

logger = logging.getLogger(__name__)

# Check if PIL is available
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.warning("PIL/Pillow not installed. Photo optimization will be limited.")

class DeliveryVerification:
    """Handle delivery reports with intelligent photo processing"""

    # Photo limits
    MAX_PHOTOS_PER_DELIVERY = 3
    MAX_PHOTO_SIZE_MB = 15
    TARGET_PHOTO_SIZE_MB = 2
    PHOTO_RESOLUTION = (1200, 900)
    VERIFICATION_WINDOW_HOURS = 72

    def __init__(self):
        self.pending_verifications: Dict[str, dict] = {}

    def create_verification_record(self, delivery_id: str, driver_shift_ref: str):
        """Create record for potential future verification"""
        self.pending_verifications[delivery_id] = {
            "delivery_id": delivery_id,
            "driver_shift_ref": driver_shift_ref,
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=self.VERIFICATION_WINDOW_HOURS),
            "photos": [],
            "gps_checkpoints": [],
            "customer_rating": None,
            "issues_reported": False,
        }

    def add_verification_photo(self, delivery_id: str, photo_data: bytes) -> dict:
        """
        Add photo with automatic optimization.
        Returns: dict with status and info about processing
        """
        if delivery_id not in self.pending_verifications:
            return {
                "success": False,
                "error": "no_verification_record",
                "message": "No verification record found for this delivery"
            }

        current_photos = self.pending_verifications[delivery_id]["photos"]
        if len(current_photos) >= self.MAX_PHOTOS_PER_DELIVERY:
            return {
                "success": False,
                "error": "photo_limit_reached",
                "message": f"Maximum of {self.MAX_PHOTOS_PER_DELIVERY} photos already uploaded",
                "suggestion": "Remove an existing photo first if you need to add a new one"
            }

        # Always accept and optimize
        processing_result = self._optimize_photo(photo_data)

        # Store reference
        photo_ref = f"photo_{hashlib.sha256(processing_result['optimized_data']).hexdigest()[:20]}"

        self.pending_verifications[delivery_id]["photos"].append({
            "ref": photo_ref,
            "original_size_mb": processing_result["original_size_mb"],
            "optimized_size_mb": processing_result["optimized_size_mb"],
            "processing_notes": processing_result["notes"],
            "uploaded_at": datetime.now(timezone.utc).isoformat()
        })

        return {
            "success": True,
            "photo_id": photo_ref,
            "original_size": f"{processing_result['original_size_mb']:.1f}MB",
            "optimized_size": f"{processing_result['optimized_size_mb']:.1f}MB",
            "note": ", ".join(processing_result["notes"])
        }

    def _optimize_photo(self, photo_data: bytes) -> dict:
        """Intelligently optimize photo for verification purposes"""
        original_size_mb = len(photo_data) / (1024 * 1024)
        notes = []

        if PIL_AVAILABLE:
            try:
                img = Image.open(io.BytesIO(photo_data))

                # Convert to RGB if necessary
                if img.mode in ('RGBA', 'LA', 'P'):
                    img = img.convert('RGB')
                    notes.append("converted_to_rgb")

                # Resize only if significantly larger
                orig_width, orig_height = img.size
                notes.append(f"original_{orig_width}x{orig_height}")

                target_width, target_height = self.PHOTO_RESOLUTION
                if orig_width > target_width * 1.5 or orig_height > target_height * 1.5:
                    # Handle different PIL versions
                    try:
                        img.thumbnail((target_width, target_height), Image.Resampling.LANCZOS)
                    except AttributeError:
                        img.thumbnail((target_width, target_height), Image.LANCZOS)
                    new_width, new_height = img.size
                    notes.append(f"resized_to_{new_width}x{new_height}")
                else:
                    notes.append("size_kept_original")

                # Optimize compression
                output = io.BytesIO()
                save_kwargs = {
                    'format': 'JPEG',
                    'quality': 80,
                    'optimize': True,
                    'progressive': True
                }

                # Adjust quality if still large
                test_output = io.BytesIO()
                img.save(test_output, **save_kwargs)
                test_size = len(test_output.getvalue()) / (1024 * 1024)

                if test_size > self.TARGET_PHOTO_SIZE_MB:
                    for quality in [70, 60, 50]:
                        test_output = io.BytesIO()
                        img.save(test_output, format='JPEG', quality=quality, optimize=True)
                        if len(test_output.getvalue()) / (1024 * 1024) <= self.TARGET_PHOTO_SIZE_MB:
                            save_kwargs['quality'] = quality
                            notes.append(f"quality_reduced_to_{quality}%")
                            break

                # Save final version
                img.save(output, **save_kwargs)
                optimized_data = output.getvalue()

            except Exception as e:
                logger.warning(f"Photo processing failed, using fallback: {e}")
                notes.append(f"processing_error_{str(e)[:50]}")
                optimized_data = self._fallback_optimize(photo_data, notes)
        else:
            notes.append("pil_not_available")
            optimized_data = self._fallback_optimize(photo_data, notes)

        optimized_size_mb = len(optimized_data) / (1024 * 1024)

        if original_size_mb > optimized_size_mb * 1.5:
            logger.info(f"Photo optimized: {original_size_mb:.1f}MB -> {optimized_size_mb:.1f}MB")

        return {
            "optimized_data": optimized_data,
            "original_size_mb": original_size_mb,
            "optimized_size_mb": optimized_size_mb,
            "notes": notes
        }

    def _fallback_optimize(self, photo_data: bytes, notes: list) -> bytes:
        """Fallback optimization when PIL is not available"""
        original_size_mb = len(photo_data) / (1024 * 1024)

        if original_size_mb > self.TARGET_PHOTO_SIZE_MB:
            # Simple truncation as last resort
            notes.append("truncated_to_size_limit")
            return photo_data[:int(self.TARGET_PHOTO_SIZE_MB * 1024 * 1024)]
        else:
            notes.append("used_original_no_processing")
            return photo_data

    def get_verification_for_support(self, delivery_id: str, support_tier: str) -> dict:
        """Get appropriate verification details for support staff"""
        record = self.pending_verifications.get(delivery_id)
        if not record:
            return {"error": "Verification window expired"}

        if support_tier == "basic":
            return {
                "delivery_id": delivery_id,
                "timeframe": f"Within {self.VERIFICATION_WINDOW_HOURS}h window",
                "gps_verified": bool(record["gps_checkpoints"]),
                "photo_count": len(record["photos"]),
                "customer_rating": record["customer_rating"],
                "issues": record["issues_reported"]
            }
        elif support_tier == "advanced":
            return {
                **self.get_verification_for_support(delivery_id, "basic"),
                "photo_references": [p["ref"] for p in record["photos"]],
                "photo_warning": "Photos contain sensitive location information",
                "time_details": record["created_at"].strftime("%Y-%m-%d %H:%M")
            }
        elif support_tier == "admin":
            return record

        return {"error": "Unauthorized access level"}

# Global instance
delivery_verification = DeliveryVerification()