from math import floor, sqrt

import cv2
import numpy as np
from cv2.typing import MatLike

from utils import MAXBYTE, ColorChannel, is_valid_image


def is_black(capture: MatLike | None):
    """Detect if the provided frame source is black."""
    if not is_valid_image(capture):
        return False, 0.0

    gray = cv2.cvtColor(capture, cv2.COLOR_BGR2GRAY)
    average = np.average(gray)

    return average < 3, average


def crop_image(capture: MatLike | None, x1, y1, x2, y2):
    """Crop an image given the dimensions."""
    if not is_valid_image(capture):
        return None

    return capture[y1:y2, x1:x2]


def get_top_third_of_capture(capture: MatLike | None):
    """Get the top third of the provided capture image."""
    if not is_valid_image(capture):
        return None

    capture_height, capture_width, _ = capture.shape
    return crop_image(capture, 0, 0, capture_width, floor(capture_height / 3))


MAXRANGE = MAXBYTE + 1
CHANNELS = (ColorChannel.Red.value, ColorChannel.Green.value, ColorChannel.Blue.value)
HISTOGRAM_SIZE = (8, 8, 8)
RANGES = (0, MAXRANGE, 0, MAXRANGE, 0, MAXRANGE)
MASK_SIZE_MULTIPLIER = ColorChannel.Alpha * MAXBYTE * MAXBYTE
MAX_VALUE = 1.0
CV2_PHASH_SIZE = 8


def compare_histograms(source: MatLike, capture: MatLike, mask: MatLike | None = None):
    """
    Compares two images by calculating their histograms, normalizing
    them, and then comparing them using Bhattacharyya distance.

    @param source: RGB or BGR image of any given width and height
    @param capture: An image matching the shape, dimensions and format of the source
    @param mask: An image matching the dimensions of the source, but 1 channel grayscale
    @return: The similarity between the histograms as a number 0 to 1.
    """
    source_hist = cv2.calcHist([source], CHANNELS, mask, HISTOGRAM_SIZE, RANGES)
    capture_hist = cv2.calcHist([capture], CHANNELS, mask, HISTOGRAM_SIZE, RANGES)

    cv2.normalize(source_hist, source_hist)
    cv2.normalize(capture_hist, capture_hist)

    return 1 - cv2.compareHist(source_hist, capture_hist, cv2.HISTCMP_BHATTACHARYYA)


def compare_l2_norm(source: MatLike, capture: MatLike, mask: MatLike | None = None):
    """
    Compares two images by calculating the L2 Error (square-root of sum of squared error)
    @param source: Image of any given shape
    @param capture: Image matching the dimensions of the source
    @param mask: An image matching the dimensions of the source, but 1 channel grayscale
    @return: The similarity between the images as a number 0 to 1.
    """
    error = cv2.norm(source, capture, cv2.NORM_L2, mask)

    # The L2 Error is summed across all pixels, so this normalizes
    max_error = (
        sqrt(source.size) * MAXBYTE
        if not is_valid_image(mask)
        else sqrt(cv2.countNonZero(mask) * MASK_SIZE_MULTIPLIER)
    )

    if not max_error:
        return 0.0
    return 1 - (error / max_error)


def __cv2_phash(source: MatLike, capture: MatLike):
    """
    OpenCV has its own pHash comparison implementation in `cv2.img_hash`,
    but is inaccurate unless we precompute the size with a specific interpolation.

    See: https://github.com/opencv/opencv_contrib/issues/3295#issuecomment-1172878684
    """
    phash = cv2.img_hash.PHash.create()
    source = cv2.resize(source, (CV2_PHASH_SIZE, CV2_PHASH_SIZE), interpolation=cv2.INTER_AREA)
    capture = cv2.resize(capture, (CV2_PHASH_SIZE, CV2_PHASH_SIZE), interpolation=cv2.INTER_AREA)
    source_hash = phash.compute(source)
    capture_hash = phash.compute(capture)
    hash_diff = phash.compare(source_hash, capture_hash)
    return 1 - (hash_diff / 64.0)


def compare_phash(source: MatLike, capture: MatLike, mask: MatLike | None = None):
    """
    Compares the Perceptual Hash of the two given images and returns the similarity between the two.

    @param source: Image of any given shape as a numpy array
    @param capture: Image of any given shape as a numpy array
    @param mask: An image matching the dimensions of the source, but 1 channel grayscale
    @return: The similarity between the hashes of the image as a number 0 to 1.
    """
    # Apply the mask to the source and capture before calculating the
    # pHash for each of the images. As a result of this, this function
    # is not going to be very helpful for large masks as the images
    # when shrunk down to 8x8 will mostly be the same.
    if is_valid_image(mask):
        source = cv2.bitwise_and(source, source, mask=mask)
        capture = cv2.bitwise_and(capture, capture, mask=mask)

    return __cv2_phash(source, capture)
