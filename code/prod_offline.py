'''
  TEXTaiLES Project
  Based on: https://github.com/DFRobot/DFRobot_EnvironmentalSensor
'''

import os
import csv
import math
import time
from datetime import datetime, timezone

# The Sensor Basic Library
from DFRobot_Environmental_Sensor import *

# --- Configuration ---
SENSOR_ID = "NAME_HERE"
# --- Readings are appended here (same folder as the script) ---
READINGS_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "readings.csv")
FIELDS = ["sensor_id", "timestamp", "temperature", "humidity", "luminosity", "atmospheric_pressure"]
# ---------------------

# Select communication mode
ctype=1 # 1 for UART, 0 for I2C

ADDRESS = 0x22
I2C_1   = 0x01

if ctype==0:
  SEN050X = DFRobot_Environmental_Sensor_I2C(I2C_1 ,ADDRESS)
else:
  SEN050X = DFRobot_Environmental_Sensor_UART(9600, ADDRESS)

# Atmospheric pressure unit select
HPA = 0x01
KPA = 0X02

# Temperature unit select
TEMP_C                    = 0X03
TEMP_F                    = 0X04

def setup():
  while (SEN050X.begin() == False):
    print("Sensor initialize failed!!")
    time.sleep(1)
  print("Sensor  initialize success!!")

def save_reading(row):
  # the header is written only when the file is new or empty
  new_file = not os.path.exists(READINGS_CSV) or os.path.getsize(READINGS_CSV) == 0
  with open(READINGS_CSV, "a", newline="") as f:
    w = csv.DictWriter(f, FIELDS)
    if new_file:
      w.writeheader()
    w.writerow(row)
    f.flush()
    os.fsync(f.fileno())  # force it to the SD card, so a power cut doesn't lose it

def loop():
  # Obtain sensor data
  temp_c = SEN050X.get_temperature(TEMP_C)
  humidity = SEN050X.get_humidity()
  uv = SEN050X.get_ultraviolet_intensity(S12DS)
  luminous = SEN050X.get_luminousintensity()
  pressure = SEN050X.get_atmosphere_pressure(HPA)
  elevation = SEN050X.get_elevation()
  
  # Print the sensorial data
  print("-----------------------\r\n")
  print("Temp: " + str(temp_c) + " 'C\r\n")
  print("Temp: " + str(SEN050X.get_temperature(TEMP_F)) + " 'F\r\n")
  print("Humidity: " + str(humidity) + " %\r\n")
  print("Ultraviolet intensity: " + str(uv) + " mw/cm2\r\n")
  print("LuminousIntensity: " + str(luminous) + " lx\r\n")
  print("Atmospheric pressure: " + str(pressure) + " hpa\r\n")
  print("Elevation: " + str(elevation) + " m\r\n")
  print("-----------------------\r\n")

  # skip invalid values (NaN/inf)
  if all(math.isfinite(v) for v in (temp_c, humidity, luminous, pressure)):
    save_reading({
        "sensor_id": SENSOR_ID,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "temperature": temp_c,
        "humidity": humidity,
       # "uv_intensity": uv,
        "luminosity": luminous,
        "atmospheric_pressure": int(pressure),
       # "elevation": elevation
    })
    print("Reading saved to " + READINGS_CSV)

  # save every 15minutes
  time.sleep(900)

if __name__ == "__main__":
  time.sleep(120) # give time to the sensor in order to initialize
  setup()
  while True:
    try:
      loop()
    except Exception as e:
      print("Error: " + str(e))
      time.sleep(60)