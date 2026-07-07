"""Output persistence and binary I/O utilities.

Writes inference results to S3 (binary outputs) and DynamoDB (status and
JSON results). Also provides shared utilities for:
    - Image decoding and encoding
    - Binary input handling (base64 and s3://)
    - Video frame extraction
    - MP4 encoding

When S3 is unavailable (no region configured or write failure) binary
output operations log a warning and return a placeholder OutputReference
rather than raising. Inference results are unaffected; only persistence
is skipped. This allows local development and testing without AWS
credentials.

A Backend abstraction (AWSBackend / LocalBackend) is planned to replace
the direct S3 client; see TODO_workflow.md.
"""

import base64
import io
import json
import logging
import os
import tempfile
from base64 import b64decode

import boto3
from botocore.exceptions import ClientError, NoRegionError
from dynawrap.backends.dynamodb import DynamoDBBackend
from PIL import Image
from shared.db_models import ResultsItem
from shared.enums import ModelType
from shared.models import OutputReference, OutputMimeType

logger = logging.getLogger(__name__)

# Maximum frames read from disk before uniform sampling is applied.
# Prevents exhausting memory on long videos before the sample is taken.
_VIDEO_READ_CAP = 512

try:
    _s3 = boto3.client("s3")
    _ddb = boto3.client("dynamodb")
    _dynawrap = DynamoDBBackend(_ddb)
except NoRegionError:
    logger.warning("no AWS region configured; S3 and DynamoDB unavailable")
    _s3 = None
    _ddb = None
    _dynawrap = None


# ---------------------------------------------------------------------------
# Image utilities
# ---------------------------------------------------------------------------


def decode_image(b64_str: str) -> Image.Image:
    """Decode a base64 image string to a PIL Image.

    Accepts raw base64 or a data-URI prefix (data:image/jpeg;base64,...).
    For http/https URLs delegates to transformers.image_utils.load_image.
    """
    if b64_str.startswith(("http://", "https://")):
        from transformers.image_utils import load_image

        return load_image(b64_str)
    if b64_str.startswith("data:"):
        b64_str = b64_str.split(",", 1)[1]
    return Image.open(io.BytesIO(b64decode(b64_str))).convert("RGB")


def image_to_png_bytes(image: Image.Image) -> bytes:
    """Encode a PIL Image to PNG bytes."""
    with io.BytesIO() as buf:
        image.save(buf, format="PNG")
        return buf.getvalue()


# ---------------------------------------------------------------------------
# Binary input utilities  (base64 and s3://)
# ---------------------------------------------------------------------------


def fetch_s3_bytes(uri: str) -> bytes:
    """Download raw bytes from an s3://bucket/key URI.

    Raises RuntimeError when the S3 client is not available (no AWS region
    configured). This is the expected failure mode in local development;
    the caller should catch it and direct the user to pass base64 input
    instead.

    Raises ValueError on a malformed URI.
    """
    if _s3 is None:
        raise RuntimeError(
            "s3:// input requires an AWS region to be configured. "
            "Pass base64-encoded input instead for local development"
        )

    path = uri[len("s3://") :]
    parts = path.split("/", 1)
    if len(parts) != 2:
        raise ValueError(
            "malformed s3:// URI: expected s3://bucket/key, got s3://%s" % path
        )

    bucket, key = parts
    response = _s3.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def decode_binary_input(input_str: str) -> bytes:
    """Decode a base64 string or s3:// URI to raw bytes.

    This is the standard input decoder for handlers that accept audio,
    video, or other binary content. For base64 input the bytes are decoded
    directly. For s3:// URIs the content is downloaded via fetch_s3_bytes.

    Raises ValueError on invalid base64.
    Raises RuntimeError when s3:// is requested without AWS credentials.
    """
    if input_str.startswith("s3://"):
        return fetch_s3_bytes(input_str)
    try:
        return base64.b64decode(input_str)
    except Exception as e:
        raise ValueError("input is not valid base64") from e


# ---------------------------------------------------------------------------
# Video utilities
# ---------------------------------------------------------------------------


def decode_video_frames(input_str: str, max_frames: int) -> list:
    """Decode a base64 or s3:// video input to a list of PIL Images.

    Writes content to a temporary file, reads up to _VIDEO_READ_CAP frames
    sequentially, then samples max_frames uniformly from the collected pool.
    The temporary file is removed before returning.

    Uses imageio for frame reading. Requires imageio and imageio-ffmpeg to
    be installed; these are lazy-imported to avoid adding them as hard
    dependencies for callers that do not process video.

    Raises ValueError if no frames could be read or if the input is invalid.
    Raises RuntimeError on s3:// input without AWS credentials.
    """
    import imageio

    raw = decode_binary_input(input_str)

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name

    try:
        reader = imageio.get_reader(tmp_path)
        all_frames = []
        try:
            for frame in reader:
                all_frames.append(Image.fromarray(frame).convert("RGB"))
                if len(all_frames) >= _VIDEO_READ_CAP:
                    break
        finally:
            reader.close()
    except Exception as e:
        raise ValueError(
            "could not read video frames; ensure the input is a valid MP4 "
            "and imageio-ffmpeg is installed"
        ) from e
    finally:
        os.unlink(tmp_path)

    if not all_frames:
        raise ValueError("no frames could be read from the video input")

    total = len(all_frames)
    if total <= max_frames:
        return all_frames

    indices = [round(i * (total - 1) / (max_frames - 1)) for i in range(max_frames)]
    return [all_frames[i] for i in indices]


def frames_to_mp4_bytes(frames: list, fps: int) -> bytes:
    """Encode a list of PIL Images to MP4 bytes via imageio-ffmpeg.

    Dimensions are rounded down to the nearest even number before encoding.
    H.264 requires even dimensions; odd-sized frames from some models would
    cause an ffmpeg error without this adjustment.

    Uses libx264, CRF 18 (visually lossless for most content), yuv420p for
    broad player compatibility.

    Requires imageio and imageio-ffmpeg; lazy-imported.
    """
    import imageio
    import numpy as np

    def _to_array(frame: Image.Image) -> "np.ndarray":
        arr = np.array(frame.convert("RGB"))
        h, w = arr.shape[:2]
        return arr[: h - (h % 2), : w - (w % 2)]

    arrays = [_to_array(f) for f in frames]

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        writer = imageio.get_writer(
            tmp_path,
            fps=fps,
            codec="libx264",
            ffmpeg_params=["-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p"],
            macro_block_size=1,
        )
        for arr in arrays:
            writer.append_data(arr)
        writer.close()

        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# S3 output writing
# ---------------------------------------------------------------------------


def write_binary_output(
    message_id: str,
    model_type: ModelType,
    field_name: str,
    data: bytes,
    mimetype: str,
) -> "OutputReference":
    """Write binary model output to S3 or the local filesystem and return an OutputReference.

    Key schema: outputs/{model_type}/{message_id}/{field_name}

    :param message_id: unique identifier for this inference request
    :param model_type: ModelType enum value, used as the S3 key prefix
    :param field_name: name of the output field, e.g. "audio", "image"
    :param data:       raw binary content to store
    :param mimetype:   MIME type of the content, stored as S3 ContentType
    :param bucket:     name of the S3 output bucket
    :returns:          OutputReference with key and mimetype

    Backend is selected by the OUTPUT_BACKEND environment variable:
      "s3"  -- write to S3 (default; requires OUTPUT_BUCKET and AWS region)
      "fs"  -- write to local filesystem under OUTPUT_DIR

    The OutputReference path contains the key for both backends. For "fs"
    the full path is OUTPUT_DIR / key. For "s3" it is the S3 object key.

    When the S3 client is unavailable or the write fails, logs the failure
    and returns an OutputReference with the intended key. Inference results
    are structurally valid; only persistence is skipped.
    """

    ext = OutputMimeType(mimetype).extension
    clean_id = message_id.removeprefix("API#")
    key = "outputs/%s/%s_%s.%s" % (model_type.value, clean_id, field_name, ext)
    backend = os.getenv("OUTPUT_BACKEND", "s3").lower()

    if backend == "fs":
        output_dir = os.getenv("OUTPUT_DIR", "")
        if not output_dir:
            logger.warning("[%s] OUTPUT_DIR not set; %s not persisted", message_id, key)
            return OutputReference(path=key, mimetype=mimetype)

        full_path = os.path.join(output_dir, key)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        try:
            with open(full_path, "wb") as f:
                f.write(data)

            logger.info("wrote %ib to %s", len(data), full_path)
        except Exception as e:
            logger.error("failed to write output to %s: %s -- output not persisted", full_path, e)

        return OutputReference(path=key, mimetype=mimetype)

    elif backend == "s3":
        if _s3 is None:
            logger.warning("[%s] s3 client unavailable; %s not persisted", message_id, key)
            return OutputReference(path=key, mimetype=mimetype)

        bucket = os.environ["OUTPUT_BUCKET"]

        try:
            _s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=data,
                ContentType=mimetype,
            )
            logger.info("wrote %ib to s3://%s/%s", len(data), bucket, key)
        except Exception as e:
            logger.error("failed to write output to s3://%s/%s: %s -- output not persisted", bucket, key, e)

        return OutputReference(path=key, mimetype=mimetype)
    else:
        raise NotImplementedError(f"Unknown backend: {backend}")


# ---------------------------------------------------------------------------
# DynamoDB
# ---------------------------------------------------------------------------


def update_results_table(
    user_id: str,
    message_id: str,
    response: dict,
    status: str = "complete",
):
    """Write a result or status update to the results cache table."""
    results_table = os.getenv("DYNAMODB_RESULTS_TABLE")

    if not results_table:
        logger.warning(
            "[%s/%s] DYNAMODB_RESULTS_TABLE not set, skipping results write",
            user_id,
            message_id,
        )
        return

    item = ResultsItem(
        user_id=user_id,
        message_id=message_id,
        status=status,
        response=json.dumps(response) if response is not None else None,
    )

    try:
        _dynawrap.save(results_table, item)
        logger.info(
            "[%s/%s] status='%s' written to dynamodb",
            user_id,
            message_id,
            status,
        )
    except ClientError as e:
        logger.critical(
            "[%s/%s] failed to write to dynamodb table '%s': %s",
            user_id,
            message_id,
            results_table,
            e,
        )
