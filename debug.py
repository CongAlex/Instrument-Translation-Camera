import cv2
from paper_detector import detect_paper


def main():
    cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("Error: Could not open webcam.")
        return

    while True:
        ret, frame = cap.read()

        if not ret:
            print("Error: Could not read frame.")
            break

        frame, mask = detect_paper(frame)

        cv2.imshow("Paper Detection", frame)
        cv2.imshow("White Pixel Mask", mask)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()