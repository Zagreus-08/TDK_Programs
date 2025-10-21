#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

// Create PCA9685 driver
Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver();

// Servo pulse limits (tweak if needed)
#define SERVOMIN 130   // 0° pulse
#define SERVOMAX 600   // 180° pulse

// Define servo channels
#define SERVO0 0  // MG996R
#define SERVO1 1  // DS Servo 20kg
#define SERVO2 2
#define SERVO3 3
#define SERVO4 4
#define SERVO5 5

// Individual target angles for each servo
int angles[6] = {90, 90, 90, 90, 90, 90}; // start at mid position

void setup() {
  Serial.begin(9600);
  Serial.println("PCA9685 6-Servo Independent Control");

  pwm.begin();
  pwm.setPWMFreq(50); // 50 Hz standard
  delay(10);

  // Move all servos to their initial (center) positions
  for (int i = 0; i < 6; i++) {
    moveServo(i, angles[i]);
    delay(200);
  }
}

void loop() {
  // Example motion pattern – each servo moves independently
  moveServoSmooth(SERVO0, 30, 120, 2);  // MG996R gentle sweep
  moveServoSmooth(SERVO1, 60, 150, 3);  // DS Servo slower movement
  moveServoSmooth(SERVO2, 45, 135, 2);
  moveServoSmooth(SERVO3, 0, 90, 3);
  moveServoSmooth(SERVO4, 90, 180, 2);
  moveServoSmooth(SERVO5, 15, 165, 2);

  delay(500);

  // Return to neutral
  for (int i = 0; i < 6; i++) {
    moveServoSmooth(i, angles[i], 90, 3);
    angles[i] = 90;
  }
  delay(2000);
}

// Convert angle to pulse
int angleToPulse(int angle) {
  return map(angle, 0, 180, SERVOMIN, SERVOMAX);
}

// Move servo instantly to angle
void moveServo(uint8_t servo, int angle) {
  int pulse = angleToPulse(angle);
  pwm.setPWM(servo, 0, pulse);
}

// Smooth motion between two angles
void moveServoSmooth(uint8_t servo, int fromAngle, int toAngle, int stepDelay) {
  if (toAngle > fromAngle) {
    for (int a = fromAngle; a <= toAngle; a++) {
      pwm.setPWM(servo, 0, angleToPulse(a));
      delay(stepDelay);
    }
  } else {
    for (int a = fromAngle; a >= toAngle; a--) {
      pwm.setPWM(servo, 0, angleToPulse(a));
      delay(stepDelay);
    }
  }
}
