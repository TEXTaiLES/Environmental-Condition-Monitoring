'''
  TEXTaiLES Project
  Based on: https://github.com/DFRobot/DFRobot_EnvironmentalSensor
'''
from __future__ import print_function
import sys
import os
sys.path.append("../")
import time
import RPi.GPIO as GPIO
import requests
import json
from datetime import datetime, timezone

# The Sensor Basic Library
from DFRobot_Environmental_Sensor import *

# Configuration for the Database
API_URL = "ADD_YOUR_API_URL"
API_KEY = "ADD_YOUR_API_KEY"
SENSOR_ID = "ADD_SENSOR_ID"

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

  # Post to API
  payload = {
      "sensor_id": SENSOR_ID,
      "timestamp": datetime.now(timezone.utc).isoformat(),
      "temperature": temp_c,
      "humidity": humidity,
      "uv_intensity": uv,
      "luminosity": luminous,
      "atmospheric_pressure": int(pressure), # Cast to int for our schema
      "elevation": elevation
  }

  headers = {
      "Authorization": "Bearer " + API_KEY,
      "Content-Type": "application/json"
  }

  try:
      response = requests.post(API_URL, json=payload, headers=headers, timeout=5)
      if response.status_code == 201:
          print("Data sent successfully. ID: " + response.json().get('id'))
      else:
          print("Failed to send data: " + str(response.status_code) + " " + response.text)
  except Exception as e:
      print("Network Error: " + str(e))

  # Send every 10s 
  time.sleep(10)

if __name__ == "__main__":
  setup()
  while True:
    loop()