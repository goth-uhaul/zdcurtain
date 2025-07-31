import os
from math import sqrt
from typing import TYPE_CHECKING

import cv2
import numpy as np
from cv2.typing import MatLike

from utils import (
    BGR_CHANNEL_COUNT,
    MAXBYTE,
    ColorChannel,
    ImageShape,
    check_if_image_has_transparency,
    imread,
    is_valid_image,
)

if TYPE_CHECKING:
    pass


# Resize to these width and height so that FPS performance increases
COMPARISON_RESIZE_WIDTH = 640
COMPARISON_RESIZE_HEIGHT = 360
COMPARISON_RESIZE = (COMPARISON_RESIZE_WIDTH, COMPARISON_RESIZE_HEIGHT)
COMPARISON_RESIZE_AREA = COMPARISON_RESIZE_WIDTH * COMPARISON_RESIZE_HEIGHT
MASK_LOWER_BOUND = np.array([0, 0, 0, 1], dtype=np.uint8)
MASK_UPPER_BOUND = np.array([MAXBYTE, MAXBYTE, MAXBYTE, MAXBYTE], dtype=np.uint8)


class ZDImage:
    image_data: MatLike | None = None
    mask_data: MatLike | None = None
    # This value is internal, check for mask instead
    _has_transparency = False

    def __init__(self, path: str):
        self.path = path
        self.filename = os.path.split(path)[-1].lower()
        self.__read_image_bytes(path)

    def __read_image_bytes(self, path: str):
        image = imread(path, cv2.IMREAD_UNCHANGED)
        if not is_valid_image(image):
            self.image_data = None
            return

        self._has_transparency = check_if_image_has_transparency(image)
        # If image has transparency, create a mask
        if self._has_transparency:
            # Adaptively determine the target size according to
            # the number of nonzero elements in the alpha channel of the split image.
            # This may result in images bigger than COMPARISON_RESIZE if there's plenty of transparency. # noqa: E501
            # Which wouldn't incur any performance loss in methods where masked regions are ignored.
            scale = min(
                1,
                sqrt(COMPARISON_RESIZE_AREA / cv2.countNonZero(image[:, :, ColorChannel.Alpha])),
            )

            image = cv2.resize(
                image,
                dsize=None,
                fx=scale,
                fy=scale,
                interpolation=cv2.INTER_NEAREST,
            )

            # Mask based on adaptively resized, nearest neighbor interpolated split image
            self.mask_data = cv2.inRange(image, MASK_LOWER_BOUND, MASK_UPPER_BOUND)
        else:
            image = cv2.resize(image, COMPARISON_RESIZE, interpolation=cv2.INTER_NEAREST)
            # Add Alpha channel if missing
            if image.shape[ImageShape.Channels] == BGR_CHANNEL_COUNT:
                image = cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)

        self.image_data = image
