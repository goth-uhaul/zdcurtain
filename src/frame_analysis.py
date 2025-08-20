from collections.abc import Callable
from math import sqrt

import cv2
import numpy as np
from cv2.typing import MatLike
from skimage.measure import shannon_entropy

from utils import MAXBYTE, ColorChannel, is_valid_image


def calculate_frame_luminance(capture: MatLike | None) -> tuple[float, float]:
    """Get the average black level and entropy of the provided capture."""
    if not is_valid_image(capture):
        return 0.0, 0.0

    gray = cv2.cvtColor(capture, cv2.COLOR_BGR2GRAY)
    average_luminance = np.average(gray)

    bins = 128
    hist, _ = np.histogram(gray.ravel(), bins=bins, range=(0, bins))

    prob_dist = 0

    if hist.sum() > 0:
        prob_dist = hist / hist.sum()

    image_entropy = shannon_entropy(prob_dist, base=2) / 7 * 100  # min 0, max debug_log(bins) = 7

    return average_luminance, image_entropy  # type: ignore - pyright float checking is bad


def crop_image(capture: MatLike | None, x1, y1, x2, y2):
    """Crop an image given the dimensions."""
    if not is_valid_image(capture):
        return None

    return capture[y1:y2, x1:x2]


MAXRANGE = MAXBYTE + 1
CHANNELS = (ColorChannel.Red.value, ColorChannel.Green.value, ColorChannel.Blue.value)
HISTOGRAM_SIZE = (8, 8, 8)
RANGES = (0, MAXRANGE, 0, MAXRANGE, 0, MAXRANGE)
MASK_SIZE_MULTIPLIER = ColorChannel.Alpha * MAXBYTE * MAXBYTE
MAX_VALUE = 1.0
CV2_PHASH_SIZE = 8
FLANN_INDEX_LSH = 6
FD_RATIO_THRESHOLD = 0.8


def compare_histograms(source: MatLike, capture: MatLike, mask: MatLike | None = None, options=None):
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


def compare_l2_norm(source: MatLike, capture: MatLike, mask: MatLike | None = None, options=None):
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


def compare_phash(source: MatLike, capture: MatLike, mask: MatLike | None = None, options=None):
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


def compare_fd_orb_bruteforce(source: MatLike, capture: MatLike, *, options=None):
    if options is None:
        options = {"nfeatures": 500, "passing_ratio": FD_RATIO_THRESHOLD}

    if not is_valid_image(source):
        return None

    if not is_valid_image(capture):
        return None

    source_grayscale = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
    capture_grayscale = cv2.cvtColor(capture, cv2.COLOR_BGR2GRAY)

    orb = cv2.ORB_create(nfeatures=options["nfeatures"])  # type: ignore  this exists, pyright

    _, source_descriptors = orb.detectAndCompute(source_grayscale, None)
    _, capture_descriptors = orb.detectAndCompute(capture_grayscale, None)

    bf = cv2.BFMatcher()  # type: ignore  not necessary

    matches = bf.knnMatch(source_descriptors, capture_descriptors, k=2)

    # need only good matches, so create a mask
    matches_mask = [[0, 0] for i in range(len(matches))]

    # perform Lowe's ratio test
    final_matches = []
    for index in range(len(matches)):
        if len(matches[index]) == 2:
            m, n = matches[index]
            if m.distance < options["passing_ratio"] * n.distance:
                matches_mask[index] = [1, 0]
                final_matches.append(matches[index])

    return len(final_matches)


def compare_fd_orb_flann(source: MatLike, capture: MatLike, *, options=None):
    if options is None:
        options = {"algorithm": FLANN_INDEX_LSH, "nfeatures": 500, "passing_ratio": FD_RATIO_THRESHOLD}

    if "algorithm" not in options:
        options["algorithm"] = FLANN_INDEX_LSH

    if not is_valid_image(source):
        return None

    if not is_valid_image(capture):
        return None

    source_grayscale = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
    capture_grayscale = cv2.cvtColor(capture, cv2.COLOR_BGR2GRAY)

    orb = cv2.ORB_create(nfeatures=options["nfeatures"])  # type: ignore  this exists, pyright

    _, source_descriptors = orb.detectAndCompute(source_grayscale, None)
    _, capture_descriptors = orb.detectAndCompute(capture_grayscale, None)

    # FLANN parameters
    index_params = {
        "algorithm": options["algorithm"],
        "table_number": 6,  # 12
        "key_size": 12,  # 20
        "multi_probe_level": 1,
    }
    search_params = {}

    flann = cv2.FlannBasedMatcher(index_params, search_params)  # type: ignore  not necessary

    flann_matches = flann.knnMatch(source_descriptors, capture_descriptors, k=2)

    # need only good matches, so create a mask
    matches_mask = [[0, 0] for i in range(len(flann_matches))]

    # perform Lowe's ratio test
    final_matches = []
    for index in range(len(flann_matches)):
        if len(flann_matches[index]) == 2:
            m, n = flann_matches[index]
            if m.distance < options["passing_ratio"] * n.distance:
                matches_mask[index] = [1, 0]
                final_matches.append(flann_matches[index])

    return len(final_matches)


def normalize_brightness_histogram(capture: MatLike):
    image_hsv = cv2.cvtColor(capture, cv2.COLOR_BGR2HSV)

    h, s, v = cv2.split(image_hsv)

    v_equalized = cv2.equalizeHist(v)

    image_hsv = cv2.merge([h, s, v_equalized])

    normalized_image = cv2.cvtColor(image_hsv, cv2.COLOR_HSV2BGR)

    return cv2.cvtColor(normalized_image, cv2.COLOR_BGR2BGRA)


def normalize_brightness_clahe(capture: MatLike):
    image_hsv = cv2.cvtColor(capture, cv2.COLOR_BGR2HSV)

    clahe = cv2.createCLAHE(clipLimit=64.0, tileGridSize=(8, 8))

    image_hsv[:, :, 2] = clahe.apply(image_hsv[:, :, 2])

    normalized_image = cv2.cvtColor(image_hsv, cv2.COLOR_HSV2BGR)

    return cv2.cvtColor(normalized_image, cv2.COLOR_BGR2BGRA)


def __compare_dummy(*_: object, options=None):
    return 0.0


def get_comparison_method_by_name(comparison_method_name: str) -> Callable:
    match comparison_method_name:
        case "l2norm":
            return compare_l2_norm
        case "histogram":
            return compare_histograms
        case "phash":
            return compare_phash
        case "orb_bf":
            return compare_fd_orb_bruteforce
        case "orb_flann":
            return compare_fd_orb_flann
        case _:
            return __compare_dummy
