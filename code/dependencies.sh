#!/bin/bash
set -e

sudo apt update
sudo apt install -y python3-pip

pip install pyserial --break-system-packages
pip install smbus --break-system-packages
pip install modbus_tk --break-system-packages