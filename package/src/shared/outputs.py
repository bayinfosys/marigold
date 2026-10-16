"""Output persistence and binary I/O utilities.

Writes binary inference outputs to the output store, and provides shared
utilities for:
    - image decoding and encoding
    - binary input handling (base64)
    - video frame extraction
    - MP4 encoding

Inputs are base64 only. The worker makes no outbound calls, so no
input is fetched from a URL.

When the output store is unavailable (not configured, or a failed
write) binary output operations log a warning and return an
OutputReference with the intended key rather than raising. Inference
results are unaffected; only persistence is skipped.
"""

import base64
import io
import logging
import os
import tempfile
from base64 import b64decode

from PIL import Image
from shared.enums import ModelType
from shared.models import OutputReference, OutputMimeType

logger = logging.getLogger(__name__)

# Maximum frames read from disk before uniform sampling is applied.
# Prevents exhausting memory on long videos before the sample is taken.
_VIDEO_READ_CAP = 512


# ---------------------------------------------------------------------------
# Image utilities
# ---------------------------------------------------------------------------


def decode_image(b64_str: str) -> Image.Image:
    """Decode a base64 image string to a PIL Image.

    Accepts raw base64 or a data-URI prefix (data:image/jpeg;base64,...).
    """
    if b64_str.startswith("data:"):
        b64_str = b64_str.split(",", 1)[1]
    return Image.open(io.BytesIO(b64decode(b64_str))).convert("RGB")


def image_to_png_bytes(image: Image.Image) -> bytes:
    """Encode a PIL Image to PNG bytes."""
    with io.BytesIO() as buf:
        image.save(buf, format="PNG")
        return buf.getvalue()


# ---------------------------------------------------------------------------
# Binary input utilities
# ---------------------------------------------------------------------------


def decode_binary_input(input_str: str) -> bytes:
    """Decode a base64 string to raw bytes.

    The standard input decoder for handlers that accept audio, video or
    other binary content.

    Raises ValueError on invalid base64.
    """
    try:
        return base64.b64decode(input_str)
    except Exception as e:
        raise ValueError("input is not valid base64") from e


# ---------------------------------------------------------------------------
# Video utilities
# ---------------------------------------------------------------------------


def decode_video_frames(input_str: str, max_frames: int) -> list:
    """Decode a base64 video input to a list of PIL Images.

    Writes content to a temporary file, reads up to _VIDEO_READ_CAP frames
    sequentially, then samples max_frames uniformly from the collected pool.
    The temporary file is removed before returning.

    Uses imageio for frame reading. Requires imageio and imageio-ffmpeg to
    be installed; these are lazy-imported to avoid adding them as hard
    dependencies for callers that do not process video.

    Raises ValueError if no frames could be read or if the input is invalid.
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
# Binary output writing
# ---------------------------------------------------------------------------


def write_binary_output(
    message_id: str,
    model_type: ModelType,
    field_name: str,
    data: bytes,
    mimetype: str,
) -> "OutputReference":
    """Write binary model output to the output store and return an OutputReference.

    Key schema: outputs/{model_type}/{message_id}_{field_name}.{ext}

    :param message_id: unique identifier for this inference request
    :param model_type: ModelType enum value, used as the key prefix
    :param field_name: name of the output field, e.g. "audio", "image"
    :param data:       raw binary content to store
    :param mimetype:   MIME type of the content
    :returns:          OutputReference with key and mimetype

    Backend is selected by the OUTPUT_BACKEND environment variable:
      "fs" (default) -- write under OUTPUT_DIR; the full path is
                        OUTPUT_DIR / key

    When the write fails, logs the failure and returns an OutputReference
    with the intended key. Inference results are structurally valid; only
    persistence is skipped.
    """
    ext = OutputMimeType(mimetype).extension
    clean_id = message_id.removeprefix("API#")
    key = "outputs/%s/%s_%s.%s" % (model_type.value, clean_id, field_name, ext)
    backend = os.getenv("OUTPUT_BACKEND", "fs").lower()

    if backend != "fs":
        raise NotImplementedError(f"unknown OUTPUT_BACKEND: {backend}")

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
