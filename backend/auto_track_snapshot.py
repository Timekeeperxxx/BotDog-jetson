from __future__ import annotations

from datetime import datetime
from pathlib import Path


async def _save_snapshot_to_disk(
    *,
    frame: bytes,
    snapshot_dir: Path,
    frame_width: int,
    frame_height: int,
) -> tuple[Path, str]:
    import numpy as np
    from PIL import Image

    now = datetime.utcnow()
    date_dir = now.strftime("%Y-%m-%d")
    filename = now.strftime("%H-%M-%S-%f") + ".jpg"
    target_dir = snapshot_dir / date_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    image_path = target_dir / filename
    image_url = f"/api/v1/static/{date_dir}/{filename}"

    frame_array = np.frombuffer(frame, dtype=np.uint8)
    frame_array = frame_array.reshape((frame_height, frame_width, 3))
    frame_array = frame_array[:, :, ::-1]
    image = Image.fromarray(frame_array)
    image.save(image_path, format="JPEG", quality=90)

    return image_path, image_url
