#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver();

#define SERVOMIN 130
#define SERVOMAX 600

void setup() {
  Serial.begin(9600);
  Serial.println("Starting Servo Test...");
  pwm.begin();
  pwm.setPWMFreq(50);
  delay(10);
}

void loop() {
  Serial.println("Moving to 0°");
  moveServo(0, 0);
  delay(1000);

  Serial.println("Moving to 90°");
  moveServo(0, 90);
  delay(1000);

  Serial.println("Moving to 180°");
  moveServo(0, 180);
  delay(1000);
}

void moveServo(uint8_t servo, int angle) {
  int pulse = map(angle, 0, 180, SERVOMIN, SERVOMAX);
  pwm.setPWM(servo, 0, pulse);
}
