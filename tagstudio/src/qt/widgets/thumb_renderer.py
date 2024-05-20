# Copyright (C) 2024 Travis Abendshien (CyanVoxel).
# Licensed under the GPL-3.0 License.
# Created for TagStudio: https://github.com/CyanVoxel/TagStudio


import logging
import math
import os
from pathlib import Path

import cv2
import rawpy  # type: ignore
from PIL import (
    Image,
    ImageDraw,
    ImageFile,
    ImageFont,
    ImageOps,
    ImageQt,
    UnidentifiedImageError,
)
from PIL.Image import DecompressionBombError
from pillow_heif import register_avif_opener, register_heif_opener  # type: ignore
from PySide6.QtCore import QObject, QSize, Signal
from PySide6.QtGui import QPixmap
from src.core.constants import (
    IMAGE_TYPES,
    PLAINTEXT_TYPES,
    RAW_IMAGE_TYPES,
    VIDEO_TYPES,
)
from src.qt.helpers.gradient import four_corner_gradient_background

ImageFile.LOAD_TRUNCATED_IMAGES = True

ERROR = "[ERROR]"
WARNING = "[WARNING]"
INFO = "[INFO]"

RESOURCES_DIR = Path(__file__).parents[3] / "resources/qt"

logging.basicConfig(format="%(message)s", level=logging.INFO)
register_heif_opener()
register_avif_opener()


class ThumbRenderer(QObject):
    updated = Signal(float, QPixmap, QSize, str)
    updated_ratio = Signal(float)

    thumb_mask_512 = Image.open(RESOURCES_DIR / "images/thumb_mask_512.png")
    thumb_mask_512.load()

    thumb_mask_hl_512 = Image.open(RESOURCES_DIR / "images/thumb_mask_hl_512.png")
    thumb_mask_hl_512.load()

    thumb_loading_512 = Image.open(RESOURCES_DIR / "images/thumb_loading_512.png")
    thumb_loading_512.load()

    thumb_broken_512 = Image.open(RESOURCES_DIR / "images/thumb_broken_512.png")
    thumb_broken_512.load()

    thumb_file_default_512 = Image.open(
        RESOURCES_DIR / "images/thumb_file_default_512.png"
    )
    thumb_file_default_512.load()

    # TODO: Make dynamic font sized given different pixel ratios
    font_pixel_ratio: float = 1
    ext_font = ImageFont.truetype(
        font=str(RESOURCES_DIR / "fonts/Oxanium-Bold.ttf"),
        size=math.floor(12 * font_pixel_ratio),
    )

    def render(
        self,
        timestamp: float,
        filepath: str,
        base_size: tuple[int, int],
        pixel_ratio: float,
        is_loading: bool = False,
        gradient: bool = False,
        update_on_ratio_change: bool = False,
    ):
        """Internal renderer. Renders an entry/element thumbnail for the GUI."""
        image: Image.Image | None = None
        pixmap: QPixmap | None = None
        final: Image.Image | None = None
        extension: str | None = None
        resampling_method = Image.Resampling.BILINEAR
        if ThumbRenderer.font_pixel_ratio != pixel_ratio:
            ThumbRenderer.font_pixel_ratio = pixel_ratio
            ThumbRenderer.ext_font = ImageFont.truetype(
                font=str(RESOURCES_DIR / "fonts/Oxanium-Bold.ttf"),
                size=math.floor(12 * ThumbRenderer.font_pixel_ratio),
            )

        adj_size = math.ceil(max(base_size[0], base_size[1]) * pixel_ratio)
        if is_loading:
            final = ThumbRenderer.thumb_loading_512.resize(
                size=(adj_size, adj_size),
                resample=Image.Resampling.BILINEAR,
            )
            qim = ImageQt.ImageQt(final)
            pixmap = QPixmap.fromImage(qim)
            pixmap.setDevicePixelRatio(pixel_ratio)
            if update_on_ratio_change:
                self.updated_ratio.emit(1)
        elif filepath:
            extension = os.path.splitext(filepath)[1][1:].lower()

            try:
                # Images =======================================================
                if extension in IMAGE_TYPES:
                    try:
                        image = Image.open(filepath)
                        if image.mode != "RGB" and image.mode != "RGBA":
                            image = image.convert(mode="RGBA")
                        if image.mode == "RGBA":
                            new_bg = Image.new(
                                mode="RGB", size=image.size, color="#1e1e1e"
                            )
                            new_bg.paste(im=image, mask=image.getchannel(3))
                            image = new_bg

                        image = ImageOps.exif_transpose(image)
                    except DecompressionBombError as e:
                        logging.info(
                            f"[ThumbRenderer]{WARNING} Couldn't Render thumbnail for {filepath} (because of {e})"
                        )

                elif extension in RAW_IMAGE_TYPES:
                    try:
                        with rawpy.imread(filepath) as raw:  # type: ignore
                            rgb = raw.postprocess()  # type: ignore
                            image = Image.frombytes(  # type: ignore
                                mode="RGB",
                                size=(rgb.shape[1], rgb.shape[0]),  # type: ignore
                                data=rgb,  # type: ignore
                                decoder_name="raw",
                            )
                    except DecompressionBombError as e:
                        logging.info(
                            f"[ThumbRenderer]{WARNING} Couldn't Render thumbnail for {filepath} (because of {e})"
                        )
                    except rawpy._rawpy.LibRawIOError:  # type: ignore
                        logging.info(
                            f"[ThumbRenderer]{ERROR} Couldn't Render thumbnail for raw image {filepath}"
                        )

                # Videos =======================================================
                elif extension in VIDEO_TYPES:
                    video = cv2.VideoCapture(filepath)
                    video.set(
                        propId=cv2.CAP_PROP_POS_FRAMES,
                        value=(video.get(cv2.CAP_PROP_FRAME_COUNT) // 2),
                    )
                    success, frame = video.read()
                    if not success:
                        # Depending on the video format, compression, and frame
                        # count, seeking halfway does not work and the thumb
                        # must be pulled from the earliest available frame.
                        video.set(propId=cv2.CAP_PROP_POS_FRAMES, value=0)
                        success, frame = video.read()
                    frame = cv2.cvtColor(src=frame, code=cv2.COLOR_BGR2RGB)
                    image = Image.fromarray(frame)

                # Plain Text ===================================================
                elif extension in PLAINTEXT_TYPES:
                    with open(filepath, "r", encoding="utf-8") as text_file:
                        text = text_file.read(256)
                    bg = Image.new(mode="RGB", size=(256, 256), color="#1e1e1e")
                    draw = ImageDraw.Draw(im=bg)
                    draw.text(xy=(16, 16), text=text, file=(255, 255, 255))  # type: ignore
                    image = bg
                # 3D ===========================================================
                # elif extension == 'stl':
                # 	# Create a new plot
                # 	matplotlib.use('agg')
                # 	figure = plt.figure()
                # 	axes = figure.add_subplot(projection='3d')

                # 	# Load the STL files and add the vectors to the plot
                # 	your_mesh = mesh.Mesh.from_file(filepath)

                # 	poly_collection = mplot3d.art3d.Poly3DCollection(your_mesh.vectors)
                # 	poly_collection.set_color((0,0,1))  # play with color
                # 	scale = your_mesh.points.flatten()
                # 	axes.auto_scale_xyz(scale, scale, scale)
                # 	axes.add_collection3d(poly_collection)
                # 	# plt.show()
                # 	img_buf = io.BytesIO()
                # 	plt.savefig(img_buf, format='png')
                # 	image = Image.open(img_buf)
                # No Rendered Thumbnail ========================================
                else:
                    image = ThumbRenderer.thumb_file_default_512.resize(
                        size=(adj_size, adj_size), resample=Image.Resampling.BILINEAR
                    )

                if not image:
                    raise UnidentifiedImageError

                orig_x, orig_y = image.size
                new_x, new_y = (adj_size, adj_size)

                if orig_x > orig_y:
                    new_x = adj_size
                    new_y = math.ceil(adj_size * (orig_y / orig_x))
                elif orig_y > orig_x:
                    new_y = adj_size
                    new_x = math.ceil(adj_size * (orig_x / orig_y))

                if update_on_ratio_change:
                    self.updated_ratio.emit(new_x / new_y)

                resampling_method = (
                    Image.Resampling.NEAREST
                    if max(image.size[0], image.size[1])
                    < max(base_size[0], base_size[1])
                    else Image.Resampling.BILINEAR
                )

                image = image.resize((new_x, new_y), resample=resampling_method)
                if gradient:
                    mask: Image.Image = ThumbRenderer.thumb_mask_512.resize(
                        size=(adj_size, adj_size), resample=Image.Resampling.BILINEAR
                    ).getchannel(3)
                    hl: Image.Image = ThumbRenderer.thumb_mask_hl_512.resize(
                        size=(adj_size, adj_size), resample=Image.Resampling.BILINEAR
                    )
                    final = four_corner_gradient_background(
                        image=image, adj_size=adj_size, mask=mask, hl=hl
                    )
                else:
                    scalar = 4
                    rec: Image.Image = Image.new(
                        mode="RGB",
                        size=tuple([d * scalar for d in image.size]),  # type: ignore
                        color="black",
                    )
                    draw = ImageDraw.Draw(im=rec)
                    draw.rounded_rectangle(
                        xy=(0, 0) + rec.size,
                        radius=(base_size[0] // 32) * scalar * pixel_ratio,
                        fill="red",
                    )
                    rec = rec.resize(
                        size=tuple([d // scalar for d in rec.size]),  # type:ignore
                        resample=Image.Resampling.BILINEAR,
                    )
                    final = Image.new(mode="RGBA", size=image.size, color=(0, 0, 0, 0))
                    final.paste(im=image, mask=rec.getchannel(0))
            except (
                UnidentifiedImageError,
                FileNotFoundError,
                cv2.error,
                DecompressionBombError,
                UnicodeDecodeError,
            ) as e:
                if e is not UnicodeDecodeError:
                    logging.info(
                        f"[ThumbRenderer]{ERROR}: Couldn't render thumbnail for {filepath} ({e})"
                    )
                if update_on_ratio_change:
                    self.updated_ratio.emit(1)
                final = ThumbRenderer.thumb_broken_512.resize(
                    (adj_size, adj_size), resample=resampling_method
                )

            qim = ImageQt.ImageQt(final)
            if image:
                image.close()
            pixmap = QPixmap.fromImage(qim)
            pixmap.setDevicePixelRatio(pixel_ratio)
        if pixmap:
            if final is None:
                raise ValueError

            self.updated.emit(
                timestamp,
                pixmap,
                QSize(
                    math.ceil(adj_size / pixel_ratio),
                    math.ceil(final.size[1] / pixel_ratio),
                ),
                extension,
            )

        else:
            self.updated.emit(timestamp, QPixmap(xpm=[]), QSize(*base_size), extension)
