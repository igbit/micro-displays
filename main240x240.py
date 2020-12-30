#   Copyright 2020 ig https://github.com/igbit igbitx@gmail.com
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

import time
import spidev
import gpiozero
import pyscreenshot as ImageGrab
import hashlib
import numpy as np

from PIL import Image, ImageDraw
from Xlib import display

SPI_SPEED_HZ = 16000000

#GND => GND
#VCC => 3.3V
SCL_GPIO = 11 # SCLK
SDA_GPIO = 10 # MOSI
RES_GPIO = 25
DC_GPIO = 24
CS_GPIO = 8 # irrelevant if the display lacks CS
#BLK => not connected

dataControlPin = None
chipSelectPin = None
resetPin = None
spiDevice = None

DISPLAY_COLS = 240
DISPLAY_ROWS = 240
DISPLAY_ROWS_HALF = int(DISPLAY_ROWS/2)
ZOOM_RECT_COLOR = "#ff0000"
ZOOM_HALF_WIDTH =int(DISPLAY_COLS/2)
ZOOM_HALF_HEIGHT = int(DISPLAY_ROWS_HALF/2)

MADCTL_Offsets_x = 0
MADCTL_Offsets_y = 0

screenWidth = 0
screenHeight = 0
xScale = 0
yScale = 0
displayWidthScaled = 0
displayHeightScaled = 0

prevResizeHash = None
prevX = None
prevY = None

def initSpiWrite(cmd):
    chipSelectPin.off() # falling edge means start of tx
    dataControlPin.off() # data control low means a command
    spiDevice.xfer([cmd & 0xFF])
    dataControlPin.on() # data control high means write to display RAM

def endSpiWrite():
    dataControlPin.off() # end of data
    chipSelectPin.on() # end of tx

def spiBufferWrite(ba):
    for start in range(0, len(ba), 4096):
        end = min(start + 4096, len(ba))
        spiDevice.xfer(ba[start:end])

def spiWrite(command, params):
    initSpiWrite(command)
    spiBufferWrite(params)
    endSpiWrite()

def setAddrWindow(x0, y0, x1, y1):
    spiWrite(0x2A,
        [0x00, x0 + MADCTL_Offsets_x, 0x00, x1 + MADCTL_Offsets_x]) # CASET
    spiWrite(0x2B,
        [0x00, y0 + MADCTL_Offsets_y, 0x00, y1 + MADCTL_Offsets_y]) # RASET

def prepareToSpiWrite(x, y, width, height):
    setAddrWindow(x, y, width, height)
    initSpiWrite(0x2C) # RAMWR

def writeImage(image, x, y, w, h):
    pb = np.array(image.convert('RGB')).astype('uint16')
    color = ((pb[:,:,0] & 0xF8) << 8) | ((pb[:,:,1] & 0xFC) << 3) | (pb[:,:,2] >> 3)
    ba = np.dstack(((color >> 8) & 0xFF, color & 0xFF)).flatten().tolist()
    prepareToSpiWrite(x, y, x + w - 1, y + h - 1)
    spiBufferWrite(ba)
    endSpiWrite()

def setupDisplay():
    resetPin.on()
    time.sleep(0.100)
    resetPin.off()
    time.sleep(0.100)
    resetPin.on()
    time.sleep(0.100)
    spiWrite(0x11,[]) # SLPOUT
    time.sleep(0.150)
    spiWrite(0x36,[0x00]) # MADCTL
    spiWrite(0x3A,[0x05]) # COLMOD
    spiWrite(0xB2,[0x0C,0x0C]) # PORCTRL 
    spiWrite(0xB7,[0x35]) # GCTRL
    spiWrite(0xBB,[0x1A]) # VCOMS
    spiWrite(0xC0,[0x2C]) # LCMCTRL
    spiWrite(0xC2,[0x01]) # VDVVRHEN
    spiWrite(0xC3,[0x0B]) # VRHS
    spiWrite(0xC4,[0x20]) # VDVS
    spiWrite(0xC6,[0x0F]) # FRCTRL2
    spiWrite(0xD0,[0xA4,0xA1]) # PWCTRL1
    spiWrite(0x21,[]) # INVON
    spiWrite(0xE0,[0x00,0x19,0x1E,0x0A,0x09,0x15,0x3D,0x44,0x51,0x12,0x03,0x00,0x3F,0x3F]) # PVGAMCTRL
    spiWrite(0xE1 ,[0x00,0x18,0x1E,0x0A,0x09,0x25,0x3F,0x43,0x52,0x33,0x03,0x00,0x3F,0x3F]) # NVGAMCTRL
    spiWrite(0x29,[]) # DISPON
    time.sleep(0.100)

def setupSpi():
    global dataControlPin
    global resetPin
    global chipSelectPin
    global spiDevice
    
    dataControlPin = gpiozero.LED(DC_GPIO)
    resetPin = gpiozero.LED(RES_GPIO)
    chipSelectPin = gpiozero.LED(CS_GPIO)

    spiDevice = spidev.SpiDev(0, 0)
    spiDevice.mode = 3
    spiDevice.lsbfirst = False
    spiDevice.max_speed_hz = SPI_SPEED_HZ

def setResolution(w,h):
    global screenWidth, screenHeight
    global xScale, yScale
    global displayWidthScaled, displayHeightScaled
    
    if screenWidth != w:
        screenWidth = w
        xScale = DISPLAY_COLS / w
        displayWidthScaled = int(DISPLAY_COLS * xScale)
        
    if screenHeight != h:
        screenHeight = h
        yScale = DISPLAY_ROWS_HALF / h
        displayHeightScaled = int(DISPLAY_ROWS_HALF * yScale)
    
def screenshot():
    global prevResizeHash, prevX, prevY
    try:
        im = ImageGrab.grab()
        w,h = im.size
        
        setResolution(w,h)
        
        data = display.Display().screen().root.query_pointer()._data
        x1 = data["root_x"]
        y1 = data["root_y"]
        
        x = int(xScale * x1)
        y = int(yScale * y1)
        rz = im.resize((DISPLAY_COLS, DISPLAY_ROWS_HALF), Image.LANCZOS)
        rzh = hashlib.md5(rz.tobytes()).hexdigest()
        if rzh != prevResizeHash or x != prevX or y != prevY:
            # todo: room for optimization if only mouse pointer has changed
            prevResizeHash = rzh
            left,upper = refreshZoom(im,w,h,x1,y1)
            a1 = int(xScale * left)
            b1 = int(yScale * upper)
            draw = ImageDraw.Draw(rz)
            draw.rectangle(((a1,b1), (a1 + displayWidthScaled, b1 + displayHeightScaled)), outline=ZOOM_RECT_COLOR)            
            writeImage(rz,0,0,DISPLAY_COLS,DISPLAY_ROWS_HALF)
        prevX = x
        prevY = y

    except Exception as inst:
        print(inst)

def refreshZoom(im,w,h,x1,y1):    
    left = x1 - ZOOM_HALF_WIDTH
    upper = y1 - ZOOM_HALF_HEIGHT
    right = x1 + ZOOM_HALF_WIDTH
    bottom = y1 + ZOOM_HALF_HEIGHT
    mouseX = ZOOM_HALF_WIDTH
    mouseY = ZOOM_HALF_HEIGHT
    if left < 0:
        mouseX = left + ZOOM_HALF_WIDTH
        left = 0
        right = DISPLAY_COLS
    if upper < 0:
        mouseY = upper + ZOOM_HALF_HEIGHT
        upper = 0
        bottom = ZOOM_HALF_WIDTH
    if right > w:
        mouseX = DISPLAY_COLS - (w-x1)
        right = w
        left = w - DISPLAY_COLS
    if bottom > h:
        mouseY = ZOOM_HALF_WIDTH - (h-y1)
        bottom = h
        upper = h - ZOOM_HALF_WIDTH
    zoomArea = (left,upper,right,bottom)
    zoom = im.crop(zoomArea)
    draw = ImageDraw.Draw(zoom)
    draw.rectangle(((mouseX,mouseY), (mouseX+5,mouseY+5)), outline=ZOOM_RECT_COLOR)
    writeImage(zoom,0,DISPLAY_ROWS_HALF,DISPLAY_COLS,DISPLAY_ROWS_HALF)
    return left,upper

if __name__ == "__main__":
    setupSpi()
    setupDisplay()

    while True:
        screenshot()
        time.sleep(0.500)
