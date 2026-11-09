'''
  TEXTaiLES Project
  Based on: https://github.com/DFRobot/DFRobot_EnvironmentalSensor
'''

import os
import csv
import math
import time
import json
import requests
from datetime import datetime, timezone

# The Sensor Basic Library
from DFRobot_Environmental_Sensor import *

# --- Configuration for the Database ---
API_URL = "DATABASE_URL"  # replace with your database URL
API_KEY = "INSERT_YOUR_API_KEY_HERE"
SENSOR_ID = "ADD_YOUR_SENSOR_ID_HERE"
# --- Unsent readings are kept here (same folder as the script) ---
PENDING_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pending_readings.csv")
FIELDS = ["sensor_id", "timestamp", "temperature", "humidity", "luminosity", "atmospheric_pressure"]
MAX_PENDING = 10000  # oldest readings are dropped beyond this, so the SD card never fills up
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

def load_pending():
  rows = []
  if os.path.exists(PENDING_CSV):
    with open(PENDING_CSV, newline="") as f:
      for r in csv.DictReader(f):
        try:
          rows.append({k: r[k] if k in ("sensor_id", "timestamp") else json.loads(r[k]) for k in FIELDS})
        except Exception:
          print("Skipping corrupt row: " + str(r))
  return rows

def save_pending(rows):
  rows = rows[-MAX_PENDING:]
  if not rows:
    if os.path.exists(PENDING_CSV):
      os.remove(PENDING_CSV)
    return
  # write to a temp file and rename, so a power cut can't corrupt the csv
  with open(PENDING_CSV + ".tmp", "w", newline="") as f:
    w = csv.DictWriter(f, FIELDS)
    w.writeheader()
    w.writerows(rows)
    f.flush()
    os.fsync(f.fileno())
  os.replace(PENDING_CSV + ".tmp", PENDING_CSV)

def send(payload):
  # True  = done (accepted, or permanently rejected by the server)
  # False = failed, try again later
  headers = {
      "Authorization": "Bearer " + API_KEY,
      "Content-Type": "application/json"
  }

  try:
      response = requests.post(API_URL, json=payload, headers=headers, timeout=5)
  except Exception as e:
      print("Network Error: " + str(e))
      return False

  if response.status_code == 201:
      print("Data sent successfully. ID: " + str(response.json().get('id')))
      return True

  print("Failed to send data: " + str(response.status_code) + " " + response.text)
  return response.status_code in (400, 413, 422)  # bad data: drop it, don't block the queue

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

  # skip invalid values (NaN/inf), they would block the queue forever
  if all(math.isfinite(v) for v in (temp_c, humidity, luminous, pressure)):
    payload = {
        "sensor_id": SENSOR_ID,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "temperature": temp_c,
        "humidity": humidity,
       # "uv_intensity": uv,
        "luminosity": luminous,
        "atmospheric_pressure": int(pressure), # Cast to int for our schema
       # "elevation": elevation
    }

    # try the current reading first
    if send(payload):
      # connection works: send the old ones too, one by one, oldest first
      pending = load_pending()
      while pending and send(pending[0]):
        pending.pop(0)
      save_pending(pending)
    else:
      # no connection: keep it in the csv for later
      save_pending(load_pending() + [payload])

  # send every 15minutes
  time.sleep(900)

if __name__ == "__main__":
  time.sleep(300) # give time to the sensor in order to initialize and establish internet connection
  setup()
  while True:
    try:
      loop()
    except Exception as e:
      print("Error: " + str(e))
      time.sleep(60)
