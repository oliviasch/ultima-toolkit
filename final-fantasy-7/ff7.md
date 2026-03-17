# ff7

<p align="center">
  <img src="https://upload.wikimedia.org/wikipedia/en/c/c2/Final_Fantasy_VII_Box_Art.jpg" alt="Cute cat">
</p>

## random_encounter_grind.py

> **huge work in progress**  
> Automates random encounter grinding in Final Fantasy VII on Steam. 


### behavior
- Continuously moves Cloud in a `WASD` loop.  
- Detects random encounters by monitoring a **specific pixel** on the screen.  
- When an encounter is detected, it spams `Enter` until the battle is completed.  

> **warning:**
> It is the *responsibility of the user* to ensure their party is prepared for non-stop battles, as there will be no healing in between. 


### setup
 Run `pip install -r requirements.txt` in terminal.


 Use the **mouse pixel monitor** in the script to find a pixel that reliably turns blue when an encounter starts.  You can probably expect this to be in the bottom left corner of your screen. Then, set `CHECK_X` and `CHECK_Y` to the coordinates of the pixel and set `TARGET_COLOR` to match the pixel’s expected RGB during encounters. Default is to just look for a large concentration of blue. Current WIP to adjust `TOLERANCE` to account for minor color variations.  

### usage
From directory with the corresponding file, run `python .\random_encounter_grind.py`. Script will run indefinity until user enters `ctrl+q`.