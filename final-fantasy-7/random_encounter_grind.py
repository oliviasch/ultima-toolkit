"""
This script is designed to automate random encounter grinding in Final Fantasy VII by monitoring a 
specific pixel on the screen for changes that indicate an encounter has started. 
When an encounter is detected, it will spam the 'Enter' key to quickly progress through battles.
"""

import pydirectinput
import pyautogui
import time
import keyboard
import threading

time.sleep(3)

running = True

# hotkey to stop the grind
def stop_loop():
    global running
    running = False
    print("Stopped!")

keyboard.add_hotkey('ctrl+q', stop_loop)

# mouse pixel config (wip)
CHECK_X = 580
CHECK_Y = 1431
TARGET_COLOR = (0, 78, 178) # does not currently work as expected
TOLERANCE = 30 

"""
If the pixel color is predominantly blue (color of the ATB menu), we assume it's an encounter. 
"""
def is_encounter(pixel):
    r, g, b = pixel
    tr, tg, tb = TARGET_COLOR

    # simply checks for a high blue rgb value
    return (
        # abs(r - tr) <= TOLERANCE and
        # abs(g - tg) <= TOLERANCE and
        b >= 100
    )

"""
Helper to print the pixel under the mouse.
"""
def mouse_pixel_monitor():
    last_pixel = None
    while running:
        x, y = pyautogui.position()
        pixel = pyautogui.pixel(x, y)
        if pixel != last_pixel:
            print(f"Mouse @({x},{y}), Pixel RGB @{pixel}")
            last_pixel = pixel
        time.sleep(0.1)

threading.Thread(target=mouse_pixel_monitor, daemon=True).start()
last_pixel = None

"""
Main grind loop.
"""
while running:
    pixel = pyautogui.pixel(CHECK_X, CHECK_Y)

    if pixel != last_pixel:
        print(f"Pixel @ ({CHECK_X},{CHECK_Y}): {pixel}")
        last_pixel = pixel

    if is_encounter(pixel):
        print(f"Encounter engaged.")

        while running:
            pixel = pyautogui.pixel(CHECK_X, CHECK_Y)
            if not is_encounter(pixel):
                break

            pydirectinput.press('enter')
            time.sleep(0.05)

        print("Battle is complete.")

    else:
        # movement loop
        for key in ['w', 'a', 's', 'd']:
            if not running:
                break

            # check before each move so we react faster
            pixel = pyautogui.pixel(CHECK_X, CHECK_Y)
            if is_encounter(pixel):
                break

            pydirectinput.press(key)
            time.sleep(0.15)