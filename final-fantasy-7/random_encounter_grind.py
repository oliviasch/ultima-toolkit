"""
This script is designed to automate random encounter grinding in Final Fantasy VII by monitoring a
specific pixel on the screen for changes that indicate an encounter has started.
When an encounter is detected, it will spam the 'Enter' key to quickly progress through battles.
"""

import threading
import time
import keyboard
import pyautogui
import pydirectinput

time.sleep(3)

running = True
mob_kills = 0

# hotkey to stop the grind
def stop_loop():
    global running
    running = False
    print("Stopped!")
    print(f"Total mobs killed: {mob_kills}")


keyboard.add_hotkey("ctrl+q", stop_loop)

# mouse pixel config (change to align with needs)
CHECK_X = 1315
CHECK_Y = 1213

"""
If the pixel color is predominantly blue (color of the ATB menu), we assume it's an encounter.
"""
def is_encounter(pixel):
    _, _, b = pixel
    return b >= 100


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
        print("Encounter engaged.")

        while running:
            pixel = pyautogui.pixel(CHECK_X, CHECK_Y)
            if not is_encounter(pixel):
                break

            pydirectinput.press("enter")
            time.sleep(0.05)

        mob_kills += 1
        print("Battle is complete.")

    else:
        # movement loop
        for key in ["w", "a", "s", "d"]:
            if not running:
                break

            # check before each move so we react faster
            pixel = pyautogui.pixel(CHECK_X, CHECK_Y)
            if is_encounter(pixel):
                break

            pydirectinput.press(key)
            time.sleep(0.05)
