import cv2
import re
import numpy as np
from paddleocr import PaddleOCR

# =========================================
# PADDLE OCR INITIALIZATION
# =========================================
ocr = PaddleOCR(
    use_textline_orientation=True,
    lang='en'
)

# =========================================
# SENSOR ID PATTERN
# Example:
# 68-21-ABCDE-123456
# =========================================
sensor_pattern = r'\b\d{2}-\d{2}-[A-Z0-9]{4,5}-\d{6}\b'

# =========================================
# OCR CONFUSION CORRECTIONS
# =========================================
OCR_CONFUSIONS = {
    'O': '0',
    'I': '1',
    'L': '1',
    'S': '5',
    'Z': '2',
    'B': '8',
    'G': '6'
}

def apply_confusions(text):
    corrected = ""

    for ch in text:
        corrected += OCR_CONFUSIONS.get(ch, ch)

    return corrected


# =========================================
# CAMERA
# =========================================
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Cannot open camera")
    exit()

print("Press Q to quit")

# =========================================
# MAIN LOOP
# =========================================
while True:

    ret, frame = cap.read()

    if not ret:
        break

    # =====================================
    # RESIZE DISPLAY
    # =====================================
    frame = cv2.resize(frame, (960, 540))

    # =====================================
    # ROI (CHANGE THIS TO YOUR SENSOR AREA)
    # =====================================
    x1, y1 = 180, 180
    x2, y2 = 780, 320

    roi = frame[y1:y2, x1:x2]

    # =====================================
    # PREPROCESSING
    # =====================================
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    gray = cv2.GaussianBlur(gray, (3, 3), 0)

    thresh = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )[1]

    # =====================================
    # UPSCALE
    # =====================================
    thresh = cv2.resize(
        thresh,
        None,
        fx=2,
        fy=2,
        interpolation=cv2.INTER_CUBIC
    )

    # =====================================
    # PADDLE OCR
    # =====================================
    ocr_input = cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)
    result = ocr.predict(ocr_input)

    detected_sensor = ""

    if result and result[0]:

        all_text = []

        for line in result[0]:

            text = line[1][0]
            confidence = line[1][1]

            if confidence > 0.5:
                all_text.append(text)

        combined_text = " ".join(all_text)

        combined_text = combined_text.upper()

        combined_text = apply_confusions(combined_text)

        # =================================
        # REGEX MATCH
        # =================================
        matches = re.findall(sensor_pattern, combined_text)

        if matches:
            detected_sensor = matches[0]

    # =====================================
    # DRAW ROI
    # =====================================
    cv2.rectangle(
        frame,
        (x1, y1),
        (x2, y2),
        (0, 255, 0),
        2
    )

    # =====================================
    # DISPLAY TEXT
    # =====================================
    if detected_sensor:

        cv2.putText(
            frame,
            f"Sensor ID: {detected_sensor}",
            (50, 60),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 255, 0),
            2
        )

        print("Detected:", detected_sensor)

    # =====================================
    # SHOW WINDOWS
    # =====================================
    cv2.imshow("Realtime Sensor OCR", frame)

    cv2.imshow("Threshold", thresh)

    # =====================================
    # EXIT
    # =====================================
    key = cv2.waitKey(1)

    if key == ord('q'):
        break

# =========================================
# CLEANUP
# =========================================
cap.release()

cv2.destroyAllWindows()