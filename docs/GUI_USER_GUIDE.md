# TuxBox Configuration GUI - User Guide

**Version:** 3.5.0
**Last Updated:** 2026-09-24

## Table of Contents

1. [Introduction](#introduction)
2. [Getting Started](#getting-started)
3. [Understanding the Interface](#understanding-the-interface)
4. [Basic Tasks](#basic-tasks)
5. [Working with Profiles](#working-with-profiles)
6. [Importing and Exporting Profiles](#importing-and-exporting-profiles)
7. [Configuring Button Mappings](#configuring-button-mappings)
8. [Using Modifier Buttons](#using-modifier-buttons)
9. [Using Double-Press Actions](#using-double-press-actions)
10. [Using Activate on Release](#using-activate-on-release)
11. [Configuring Haptic Feedback](#configuring-haptic-feedback)
12. [Configuring Modifier Key Delay](#configuring-modifier-key-delay)
13. [Global Settings](#global-settings)
14. [Tips & Tricks](#tips--tricks)
15. [Checking for Updates](#checking-for-updates)
16. [Troubleshooting](#troubleshooting)


---

## Introduction

The TuxBox Configuration GUI is a graphical application that lets you configure your TourBox controller without manually editing configuration files. With this tool, you can:

- **Visually configure** all 20 controls (buttons, dials, scroll wheel, knob)
- **Press physical buttons** on your TourBox to instantly select controls for editing
- **Create over 250 unique key combinations per profile** using modifier buttons
- **Assign double-press actions** to buttons for even more shortcuts
- **Create application-specific profiles** that automatically switch based on the active window
- **Import and export profiles** to share with other users
- **Configure haptic feedback** for rotary controls (knob, scroll wheel, dial)
- **Manage multiple profiles** with an intuitive interface
- **Test configurations** without leaving the Configuration GUI

---

## Getting Started

### Launching the GUI

Simply run:

```bash
tuxbox-gui
```

**What happens on launch:**

1. If you have a legacy config (`mappings.conf`), it will be automatically migrated to individual profile files
2. Loads your profiles from `~/.config/tuxbox/profiles/`
3. Displays all profiles and button mappings

**On exit:**

- Prompts you to save any unsaved changes

> **Note:** The driver continues running while the GUI is open. When you save changes, the configuration is automatically reloaded and applied without restarting the driver.

---

## Understanding the Interface

![TuxBox Configuration GUI](images/gui-screenshot.png?v=3.1.0)

The GUI has a 4-panel layout:

```
+---------------------+--------------------------+
|                     |                          |
|  1. Controller      |  2. Controls             |
|     View            |     Configuration        |
|                     |     (Button List)        |
|  (Visual TourBox)   |                          |
|                     |                          |
+---------------------+--------------------------+
|                     |                          |
|  3. Profiles        |  4. Control Editor       |
|                     |                          |
|  (Profile List)     |  (Edit Mappings)         |
|                     |                          |
+---------------------+--------------------------+
```

### 1. Controller View (Top-Left)

- **Visual representation** of the TourBox controller
- **Highlights controls** when you select them from the list
- Shows which button you're currently editing

### 2. Profiles (Bottom-Left)

- **List of all available profiles** with three columns:
  - **Name** - Profile name (with warning icon if conflicts exist)
  - **Window** - Window matching rules (app_id or window_class)
  - **Active** - Checkbox to enable/disable the profile
- The **default profile** is always present, cannot be deleted, and is always active
- **Active checkbox** - Controls whether a profile participates in automatic window matching:
  - Checked: Profile will activate when its window rules match
  - Unchecked: Profile is disabled and will be skipped during matching
  - Changes take effect immediately (no save required)
- **Conflict warning** - Profiles with an orange **!** icon have conflicting window rules with another active profile. Hover to see which profiles conflict. Only the first alphabetically will be used.
- Buttons to **create**, **edit**, **delete**, **import**, and **export** profiles

### 3. Controls Configuration (Top-Right)

- **Table showing all 20 controls** with their current mappings
- Displays human-readable action names (e.g., "Ctrl+C", "Scroll Up", "Right Click")
- Click any control to **select it for editing**
- Shows "(unmapped)" for controls with no action assigned

### 4. Control Editor (Bottom-Right)

- **Configure the selected control's action**
- Choose action type: Keyboard, Mouse, or None
- Set modifier keys (Ctrl, Alt, Shift, Super)
- Select keys, mouse scroll directions, or mouse button clicks
- Configure double-press actions for buttons
- Create and edit modifier combinations
- **Apply** button saves changes to memory (not actually saved to the config file yet)

### Menu Bar & Toolbar

- **File Menu:**
  - Save (Ctrl+S) - Write changes to config file and apply them
  - Import Profile - Import a profile
  - Export Profile - Export a profile
  - Global Settings - Edit settings that apply to the whole driver (see [Global Settings](#global-settings))
  - Restart Driver - Restart the TuxBox driver service and reload profiles
  - Quit - Exit the application

- **Help Menu:**
  - Check for Updates - Check GitHub for a newer version
  - User Guide - Open this documentation
  - About - Show version and author information

- **Toolbar:** Quick access button for Save

- **Status Bar:** Shows current status, profile name, and operation feedback

### Using Physical Buttons to Select Controls

You can **press any button or rotate any dial on your TourBox** to instantly select that control for editing in the GUI. This is much faster than clicking through the Controls Configuration table.

**How it works:**
- The driver includes a built-in `TuxBox GUI` profile that activates when the GUI window is focused
- Physical button presses are mapped to keyboard shortcuts that the GUI recognizes
- The GUI automatically selects the corresponding control for editing

**Example:** To edit the "knob clockwise" mapping:
1. Make sure the GUI window is focused
2. Rotate the knob clockwise on your TourBox
3. The "Knob Clockwise" control is automatically selected in the Controls Configuration table
4. The Control Editor loads the current mapping, ready to edit

> **Note:** This requires the TuxBox driver to be running. If you stopped the driver for testing, physical button selection won't work until you restart it.

---

## Basic Tasks

### Task 1: Change a Button Mapping

**Example:** Change the "side" button to Ctrl+C (copy)

1. **Select the profile** you want to edit from the Profiles list (e.g., "default")
2. **Click "side"** in the Controls Configuration table
   - The controller view highlights the side button
   - The Control Editor loads the current mapping
3. In the Control Editor:
   - Select **"Keyboard"** as the action type
   - Check the **"Ctrl"** modifier box
   - Type **"c"** in the **"Key:"** text input field
4. Click **"Apply"**
   - The Controls Configuration table updates to show "Ctrl+C"
   - Window title shows an asterisk (*) indicating unsaved changes
5. Click **"Save"** (toolbar or Ctrl+S)
   - Creates a timestamped backup of your profile
   - Writes the changes to `~/.config/tuxbox/profiles/<profile>.profile`
   - Automatically applies the new configuration
   - Success dialog confirms the save

**Result:** The "side" button now immediately sends Ctrl+C when pressed! The new configuration was applied automatically.

### Task 2: Create a New Application-Specific Profile

**Example:** Create a profile for Visual Studio Code

1. Click the **"+"** button below the Profiles list
2. In the dialog:
   - Enter profile name: **"vscode"** and click **OK**
   - Choose **Yes** if you would like to copy settings for the currently selected profile
3. The new profile is created and selected
4. A dialog appears asking if you would like to set up window matching rules:
   - Click **Yes**
   - Click **"Capture Active Window"**
   - A dialog box appears giving you 5 seconds to click on VS Code window
   - The GUI auto-fills the App ID and Window Class fields
   - Click **Apply**
5. Customize button mappings for VS Code (see Task 1)
6. Click **"Save"** to write the profile to config

**Result:** When you focus a VS Code window, this profile automatically activates!

### Task 3: Test Your Configuration

**Example:** Test button mappings with the physical device

1. Make changes to button mappings (see Task 1)
2. Click **"Save"** (toolbar or Ctrl+S)
   - Changes are written to config and applied automatically
3. **Switch to your target application** (e.g., text editor, browser)
4. **Press buttons on your physical TourBox**
   - Actions are sent immediately to your application
   - Verify that mappings work as expected
5. **Switch back to the GUI** to make further adjustments if needed

**Result:** You can rapidly iterate: edit -> save -> test in app -> edit -> save without closing anything!

---

## Working with Profiles

### What Are Profiles?

Profiles are **collections of button mappings** that can automatically activate based on the active application window. This lets you have different button behaviors for different programs.

**Example use cases:**
- **Default profile:** General mappings for desktop navigation
- **GIMP profile:** Brush size, zoom, undo for image editing
- **Firefox profile:** Tab switching, zoom, page navigation
- **VS Code profile:** Comment code, find, formatting shortcuts

### The Default Profile

- Always present and **cannot be deleted**
- Used when no other profile matches the active window
- Good place to put general-purpose mappings

### Creating Profiles

**Two ways to create a profile:**

1. **Based on selected profile**
   - Copies all button mappings from the currently selected profile
   - Good starting point - customize from there
   - Saves time vs. configuring everything from scratch

2. **Empty profile**
   - No mappings configured
   - All controls show "(unmapped)"
   - Good if you want a completely custom layout

**Steps:**
1. Click **"+"** button
2. Enter a unique name
3. Choose copy or empty
4. Configure window matching rules (next section)

### Window Matching Rules

Profiles activate when the window properties match your rules. You can match by:

- **App ID** - Wayland application identifier (e.g., `code`, `firefox`)
- **Window Class** - X11/Wayland window class (e.g., `firefox-esr`, `Code`)

**Capturing Window Info Automatically:**

1. Open the application that you want to match the profile to
2. In the TuxBox GUI, select the profile want to set the window matching for
3. Click the **"settings"** (settings) button in the Profiles pane
4. Click the **"Capture Active Window"** button
5. **Within 5 seconds**, click on the app window you want to match to
6. After 5 seconds, the GUI auto-fills the App ID and Window Class fields
7. Click **Apply**
8. Click **Save** (just under the File Menu)

**Tips:**
- You can use **one, or both** matching fields
- Any one of the fields must match for the profile to activate
- Leave fields blank to ignore that matching criterion
- We recommend you leave/use both matching methods

### Editing Profiles

1. Select the profile in the Profiles list
2. Click the **"settings"** (settings) button
3. Edit name and/or window matching rules
4. Click **Apply** (changes saved to memory)
5. Click **Save** button to write to config file

> **Note:** You cannot edit the default profile's settings (name/window matching) - only its button mappings.

### Deleting Profiles

1. Select the profile to delete
2. Click the **"-"** button
3. Confirm deletion in the dialog

> **Warning:** Deletion is permanent!

### Enabling and Disabling Profiles

Each profile has an **Active** checkbox that controls whether it participates in automatic window matching.

**To enable/disable a profile:**
1. Find the profile in the Profiles list
2. Click the checkbox in the **Active** column
3. The change takes effect immediately (driver reloads automatically)

**Use cases for disabling profiles:**
- **Multiple profiles for the same app** - Create variants (e.g., "VS Code - Editing" and "VS Code - Debugging") and enable only the one you want active
- **Temporary disable** - Turn off a profile without deleting it
- **Testing** - Disable app-specific profiles to test with the default profile

> **Note:** The default profile is always active and cannot be disabled.

### Profile Conflicts

When two or more **active** profiles match the same application (same window_class or app_id), a conflict exists. The GUI warns you about this:

- Conflicting profiles show an orange **!** icon next to their name
- Hover over the profile name to see which profiles it conflicts with
- Only the **first profile alphabetically** will be used when the application is focused

**To resolve a conflict:**
1. **Disable one profile** - Uncheck the Active box for profiles you don't want to use
2. **Change window matching** - Edit one profile's app_id/window_class to be more specific
3. **Rename** - If you want a different profile to take priority, rename it to sort first alphabetically

**Example conflict:**
- "VS Code" profile with `window_class = Code`
- "VS Code Dev" profile with `window_class = Code`

Both match VS Code windows. "VS Code" wins because it sorts before "VS Code Dev" alphabetically. To use "VS Code Dev" instead, disable "VS Code" by unchecking its Active box.

### Profile Switching

When the TuxBox driver is running:

- The driver monitors the active window (immediately on KDE Plasma, otherwise every 0.2s by default)
- Compares window properties against all **active** profile rules
- Switches to the first matching profile (alphabetically if multiple match)
- Falls back to default if no match

**In the GUI:**
- Simply click a profile name to switch to it
- The Controls Configuration table updates

---

## Importing and Exporting Profiles

### Why Import/Export?

- **Share profiles** with other TourBox users
- **Backup** your custom configurations
- **Transfer** profiles between computers
- **Community sharing** - download profiles from other users

### Exporting a Profile

1. **Select the profile** you want to export in the Profiles panel
2. **Click the Export button** (or use **File > Export Profile...**)
3. **Choose a location** and filename in the save dialog
4. **Click Save** to create the `.profile` file

The exported file contains all profile settings:
- Button and rotary control mappings
- Modifier button configurations
- Haptic feedback settings
- Window matching rules
- Comments

### Importing a Profile

1. **Click the Import button** (or use **File > Import Profile...**)
2. **Select a `.profile` file** to import
3. **Handle name conflicts** (if any):
   - **Replace** - Delete existing profile and import the new one
   - **Rename** - Give the imported profile a new name
4. **The profile appears** in your Profiles panel

### Configuration Migration

When you first launch the GUI after upgrading to version 2.3.0 or later, you may see a migration dialog. This converts your existing configuration from the old single-file format to the new individual profile files.

**Benefits of migration:**
- Each profile is stored as a separate `.profile` file
- Easy to share, backup, and manage profiles
- Better organization for users with many profiles

**Migration is safe:**
- Your original configuration is backed up
- Your existing profile settings are preserved during migration

---

## Configuring Button Mappings

### The 20 TourBox Controls

Your TourBox has these controls:

**Buttons (7):**
- `side` - Large side button
- `top` - Top button
- `tall` - Tall button (bottom-left)
- `short` - Short button (bottom-right)
- `c1` - C1 button
- `c2` - C2 button
- `tour` - Tour button (center)

**D-Pad (4):**
- `dpad_up`, `dpad_down`, `dpad_left`, `dpad_right`

**Scroll Wheel (3):**
- `scroll_up` - Scroll wheel up
- `scroll_down` - Scroll wheel down
- `scroll_click` - Press the scroll wheel

**Knob (3):**
- `knob_cw` - Rotate knob clockwise
- `knob_ccw` - Rotate knob counter-clockwise
- `knob_click` - Press the knob

**Dial (3):**
- `dial_cw` - Rotate dial clockwise
- `dial_ccw` - Rotate dial counter-clockwise
- `dial_click` - Press the dial

### Action Types

Each control can be mapped to one of these action types:

#### 1. Keyboard Action

Send a keyboard key press (with optional modifiers).

**Modifiers:** (can combine multiple)
- Ctrl
- Alt
- Shift
- Super (Windows/Command key)

**Keys:**
- **Typeable characters:** Just type them in the text field
  - Letters: a-z (lowercase sends lowercase, uppercase sends uppercase)
  - Numbers: 0-9
  - Symbols: `-` `=` `[` `]` `;` `'` `` ` `` `\` `,` `.` `/`

- **Special keys:** Select from dropdown
  - Control: Enter, Escape, Tab, Space, Backspace, Delete, Insert
  - Arrows: Up, Down, Left, Right
  - Navigation: Home, End, Page Up, Page Down
  - Function: F1-F12
  - Zoom: Zoom In, Zoom Out, Zoom Reset
  - Other: Context Menu

**Examples:**
- `Ctrl+C` - Click Ctrl, type "c"
- `Ctrl+Shift+Z` - Click Ctrl and Shift, type "z"
- `Alt+F4` - Click Alt, select "F4" from dropdown
- `]` - Just type "]" (closing bracket)
- `Super` - Click Super only (no key)

**Tips:**
- Either use the **text input** OR the **dropdown**, not both
- Modifier-only mappings are valid (e.g., just "Ctrl" or "Alt")
- The GUI shows human-readable names in the controls list

#### 2. Mouse

Simulate mouse actions including scrolling and button clicks, with optional modifier keys.

**Modifiers:** (can combine multiple)
- Ctrl
- Alt
- Shift
- Super (Windows/Command key)

**Scroll Actions:**
- Scroll Up - Scroll up
- Scroll Down - Scroll down
- Scroll Left - Scroll left (for apps that support horizontal scrolling)
- Scroll Right - Scroll right

**Button Actions:**
- Left Click - Simulate left mouse button click
- Right Click - Simulate right mouse button click (context menu)
- Middle Click - Simulate middle mouse button click

**Common uses:**
- Map `Knob Clockwise` to Scroll Up and `Knob Counter-CW` to Scroll Down for scrolling
- Map `Dial Clockwise`/`Dial Counter-CW` to **Ctrl+Scroll Up/Down** for zooming in most applications
- Map a button to Right Click to open context menus without moving your hand to the mouse
- Map Middle Click for paste operations in terminals or opening links in new tabs
- Map **Ctrl+Left Click** for multi-select in file managers and list views
- Map **Shift+Left Click** for range selection

#### 3. None (Unmapped)

The control does nothing when pressed.

**Use cases:**
- Disable a button you don't use
- Temporarily disable a control while testing
- Prevent accidental presses

---

## Using Modifier Buttons

### What Are Modifier Buttons?

**Modifier buttons** are a powerful feature that allows you to create **over 250 unique key combinations per profile** using your TourBox's physical buttons. When a button acts as a modifier, it can be combined with any other control to trigger different actions.

**Example Workflow:**
- `Side` button alone -> Send Super key (open application menu)
- `Side + Top` button -> Send Ctrl+C (copy)
- `Side + Tall` button -> Send Ctrl+V (paste)
- `Side + Short` button -> Send Ctrl+Z (undo)
- `Side + C1` button -> Send Ctrl+Shift+Z (redo)
- ... and so on!

This gives you multiple "layers" of functionality from the same physical buttons, similar to how Shift, Ctrl, and Alt keys work on your keyboard.

### Which Buttons Can Be Modifiers?

The **14 physical buttons** that can act as modifiers:

**Main Buttons (7):**
- side, top, tall, short, c1, c2, tour

**D-Pad Buttons (4):**
- dpad_up, dpad_down, dpad_left, dpad_right

**Click Buttons (3):**
- scroll_click, knob_click, dial_click

**Note:** Only the **rotational movements** cannot be modifiers:
- scroll_up/scroll_down (scroll wheel rotation)
- knob_cw/knob_ccw (knob rotation)
- dial_cw/dial_ccw (dial rotation)

However, the **click actions** (scroll_click, knob_click, dial_click) **can** be modifiers and can also be combined with other modifiers.

### Configuring a Modifier Button

**Example:** Make the "side" button a modifier

1. **Select the profile** you want to edit (e.g., "default")
2. **Click the "side" button** in the Controls Configuration table
3. In the Control Editor:
   - Configure the **base action** (what happens when pressed alone):
     - Select **"Keyboard"** as the action type
     - Check the **"Super"** modifier
     - Leave the key field empty (modifier-only action)
   - Click **"Apply"** to save the base action
4. You can now add combinations (see next section)

**Important:** A button becomes a modifier **automatically** when it has at least one modifier combination defined. There's no checkbox to enable/disable modifier mode - it's determined by whether combinations exist.

### Adding Modifier Combinations

**Example:** Add "Side + Top = Ctrl+C" combination

1. **Ensure the modifier button is selected** (e.g., "side")
2. In the **Modifier Combinations** section (bottom of Control Editor):
   - Click **"Add Combination"**
3. In the dialog that appears:
   - **Control:** Select "top" from the dropdown
   - **Action Type:** Select "Keyboard"
   - **Modifiers:** Check "Ctrl"
   - **Key:** Type "c"
   - **Comment:** (Optional) Type "Copy"
   - For dial controls you can select the **Strength** and **Speed** of the haptic feedback
   - Click **"OK"**
4. The combination appears in the Modifier Combinations table
5. Click **"Apply"** to apply changes
6. Click **"Save"** (Ctrl+S) to write to config file (You must save any changes to make them permanent and to test your mappings)

**Result:** Now when you hold the "side" button and press "top", it sends Ctrl+C!

### Editing and Deleting Combinations

**To edit a combination:**
1. Select the modifier button in Controls Configuration
2. In the Modifier Combinations table, click the combination row
3. Click the **"Edit"** button in the rightmost column
4. Make changes in the dialog
5. Click **"OK"**, then **"Apply"**, then **"Save"**

**To delete a combination:**
1. Select the modifier button in Controls Configuration
2. In the Modifier Combinations table, click the combination row
3. Click the **"Delete"** (trash icon) button in the rightmost column
4. Confirm deletion
5. Click **"Apply"**, then **"Save"**

### How Modifier Buttons Work

**Press behavior:**
- **Hold modifier + press another control** -> Sends the combination action
- **Press and release modifier alone** -> Sends the base action

**Visual feedback:**
- When a modifier button is selected, you'll see its **base action** in the "Current Action" column
- The **Modifier Combinations** section shows all defined combinations for that button
- When you click a combination in the table, both the modifier button **and** the combination control are highlighted in the controller view

### Common Modifier Patterns

**Text Editing (Side as modifier):**
- `side + tall` -> Ctrl+C (copy)
- `side + short` -> Ctrl+V (paste)
- `side + c1` -> Ctrl+Z (undo)
- `side + c2` -> Ctrl+Shift+Z (redo)
- `side + tour` -> Ctrl+A (select all)
- `side` alone -> Super (application menu)

**Navigation (Top as modifier):**
- `top + dpad_up` -> Page Up
- `top + dpad_down` -> Page Down
- `top + dpad_left` -> Home
- `top + dpad_right` -> End
- `top + scroll_up` -> Ctrl+Home (document start)
- `top + scroll_down` -> Ctrl+End (document end)
- `top` alone -> Shift

**Application-Specific (Tall as modifier for GIMP/Photoshop):**
- `tall + knob_cw` -> Increase brush size
- `tall + knob_ccw` -> Decrease brush size
- `tall + c1` -> Switch to brush tool
- `tall + c2` -> Switch to eraser tool
- `tall + tour` -> Reset tool options
- `tall` alone -> Alt

**Context Menu Navigation (C1 as modifier):**

This pattern lets you navigate context menus entirely from your TourBox - open the menu, scroll through options, and select - without touching your mouse:

- `c1` alone -> Right Click (opens context menu)
- `c1 + scroll_up` -> Up Arrow (navigate menu up)
- `c1 + scroll_down` -> Down Arrow (navigate menu down)
- `c2` -> Left Click or Enter (select menu item)

**Workflow:**
1. Hold C1 -> right-click opens the context menu
2. While still holding C1, scroll up/down -> arrow keys navigate the menu
3. Release C1, press C2 -> selects the highlighted item

This effectively recreates the overlay menu experience using native application context menus!

### Tips for Using Modifiers

**1. Keep Base Actions Useful**
- Don't set the base action to "None" - you'll lose functionality when pressing the button alone
- Good base actions: Super, Shift, Alt, Ctrl (modifier keys)
- These are useful both alone and in combinations

**2. Organize by Function**
- Group related combinations under one modifier button
- Example: All text editing under "side", all navigation under "top"

**3. Start Simple**
- Begin with 3-4 combinations per modifier
- Add more as you memorize them
- Too many combinations can be overwhelming

**4. Use Comments**
- Add descriptive comments to combinations
- Helps you remember what each combination does
- Especially useful for complex shortcuts

**5. Profile-Specific Modifiers**
- Different profiles can have different modifier combinations
- Example: "side + c1" = Ctrl+Z in default, but "Undo Brush Stroke" in GIMP profile
- The same physical buttons can do completely different things per application

### Example: Complete Modifier Setup

Here's a complete example showing how to set up a modifier-heavy workflow:

**Side Button (Modifier):**
- Base action: Super
- Combinations:
  - side + top -> Ctrl+C (copy)
  - side + tall -> Ctrl+V (paste)
  - side + short -> Ctrl+X (cut)
  - side + c1 -> Ctrl+Z (undo)
  - side + c2 -> Ctrl+Shift+Z (redo)
  - side + tour -> Ctrl+A (select all)
  - side + dpad_up -> Ctrl+Home
  - side + dpad_down -> Ctrl+End
  - side + knob_cw -> Ctrl+= (zoom in)
  - side + knob_ccw -> Ctrl+- (zoom out)

**Top Button (Regular):**
- Action: Shift (no combinations)

**Result:** You've created 10 additional shortcuts from just the "side" button, while keeping "top" as a simple Shift key!

### Troubleshooting Modifiers

**Problem:** Combination doesn't trigger

**Solutions:**
1. Verify the combination exists in the Modifier Combinations table
2. Check that you're holding the modifier button while pressing the other control
3. Ensure you clicked "Apply" and "Save" after adding the combination
4. Check driver logs: `journalctl --user -u tuxbox -f`
5. Restart the driver: `systemctl --user restart tuxbox`

**Problem:** Base action doesn't work when pressed alone

**Solutions:**
1. Verify the base action is configured (check "Current Action" column)
2. Make sure you're **not** holding the modifier button too long
3. Release the modifier button cleanly without pressing other controls

**Problem:** Too many combinations to remember

**Solutions:**
1. Use the comment field to document what each combination does
2. Print a reference card with your most-used combinations
3. Start with fewer combinations and add more gradually
4. Group related functions under the same modifier

---

## Using Double-Press Actions

### What Are Double-Press Actions?

**Double-press actions** allow you to assign a second action to a button that triggers when you quickly press the button twice (like a double-click). This effectively doubles the number of actions you can assign to each button without using modifiers.

**Example:**
- Press `Side` button once -> Send Super key (open application menu)
- Double-press `Side` button quickly -> Send Ctrl+Alt+T (open terminal)

### Which Buttons Support Double-Press?

All **14 physical buttons** can have double-press actions:

**Main Buttons (7):**
- side, top, tall, short, c1, c2, tour

**D-Pad Buttons (4):**
- dpad_up, dpad_down, dpad_left, dpad_right

**Click Buttons (3):**
- scroll_click, knob_click, dial_click

**Note:** Rotary controls (scroll_up/down, knob_cw/ccw, dial_cw/ccw) do **not** support double-press because they are continuous rotation events, not discrete button presses.

### Configuring a Double-Press Action

**Example:** Add a double-press action to the "side" button

1. **Select the profile** you want to edit (e.g., "default")
2. **Click the "side" button** in the Controls Configuration table
3. In the Control Editor, find the **"Double-Press Action"** section
4. Click the **"Configure..."** button to open the Double-Press Action dialog
5. In the dialog:
   - Select **"Keyboard"** as the action type
   - Check **"Ctrl"** and **"Alt"** modifier boxes
   - Type **"t"** in the key field
   - Click **"OK"**
6. Click **"Apply"** to save changes to memory
7. Click **"Save"** (Ctrl+S) to write to config file

**Result:** The Controls Configuration table now shows "Super (2x: Ctrl+Alt+T)" indicating both the single-press and double-press actions!

### Clearing a Double-Press Action

To remove a double-press action and keep only the single-press:

1. **Select the button** in the Controls Configuration table
2. In the **"Double-Press Action"** section, click **"Clear"**
3. Click **"Apply"**, then **"Save"**

The "(2x: ...)" suffix disappears from the Current Action column.

### Understanding the Double-Press Timeout

Double-press detection uses a **timeout window** to distinguish between single and double presses:

**Default timeout:** 300ms (adjustable per profile from 50ms to 500ms)

**To change the timeout:**
1. Select the profile in the Profiles list
2. Click the **"settings"** (settings) button
3. Find the **"Double-Click"** section
4. Use the **slider** for quick 50ms adjustments, or type an exact value in the **spin box**
5. Click **"Apply"**, then **"Save"**

### How Immediate Fire Works (Default)

The driver uses **immediate fire** by default - base actions fire instantly with **zero latency**:

**Example:** Button with Space (pan) + double-press Shift:
1. **First press** -> Space DOWN immediately (pan starts!)
2. **First release** -> Space UP (pan stops)
3. **Second press within timeout** -> Shift DOWN (double-press detected!)
4. **Second release** -> Shift UP

**Key benefit:** Hold actions (pan, zoom) work perfectly because the key fires immediately on press.

**The trade-off:** If you double-press, you get a quick tap of the base action before the double-press action. For most workflows, this is acceptable and preferable to latency.

### Timeout Recommendations

- **100-150ms**: Very tight timing, requires fast fingers, fewer accidental triggers
- **200-250ms**: Good balance for experienced users
- **300ms** (default): Safe default for most users, reliable double-press detection
- **400-500ms**: Very forgiving, easier to hit double-press

### Tips for Using Double-Press Actions

**1. Choose Appropriate Actions**

- **Single-press:** Frequently used actions where speed matters
- **Double-press:** Less frequent actions where slight delay is acceptable

**Example:**
- Single-press: Undo (Ctrl+Z) - used constantly
- Double-press: Undo history dialog (Ctrl+Alt+Z) - used occasionally

**2. Choose Your Timeout**

- **100-150ms**: Tight timing, fewer accidental triggers
- **200-250ms**: Good balance for experienced users
- **300ms** (default): Safe default, reliable detection
- **400-500ms**: More forgiving for slower double-taps

**3. Combine with Modifiers**

Double-press works with modifier buttons! You can have:
- `Side` alone -> Super key
- `Side` double-press -> Ctrl+Alt+T
- `Side + Top` -> Ctrl+C (combo)

All three actions from one button!

**4. Use for Toggle Actions**

Double-press is great for toggles:
- Single-press: Play/Pause
- Double-press: Stop

Or mode switches:
- Single-press: Brush tool
- Double-press: Eraser tool

### Troubleshooting Double-Press

**Problem:** Double-press action doesn't trigger

**Solutions:**
1. Press faster - both presses must be within the timeout window
2. Increase the timeout in Profile Settings
3. Verify the double-press action is configured (look for "(2x: ...)" in Current Action)
4. Check that you clicked "Apply" and "Save" after configuring

**Problem:** Accidentally triggering double-press

**Solutions:**
1. Reduce the timeout to 100-150ms in Profile Settings
2. This creates a tighter window so normal button presses don't accidentally trigger double-press

**Problem:** Combo fires base action AND combo action

**Solutions:**
1. This can happen if you press the combo button too slowly
2. Try pressing the combo button more quickly after the modifier
3. Enable "Activate on release" for the modifier button for cleaner combos (see next section)

---

## Using Activate on Release

### What Is "Activate on Release"?

**Activate on release** is a button behavior option that changes when a button's action fires:

- **Normal behavior (off):** Action fires immediately when button is pressed
- **Activate on release (on):** Action fires when button is released, as a quick tap (press+release together)

This option is especially useful for **modifier buttons** where you need reliable combo detection.

### Why Use Activate on Release?

**The Problem with Modifiers:**

When you configure a button as a modifier (with combos), pressing it needs to do two things:
1. Track that the modifier is held (for combo detection)
2. Optionally fire a base action (like Ctrl or Shift)

Without "Activate on release", the base action fires immediately on press. If you're slightly slow pressing the combo button, you get:
- Base action fires (e.g., Space)
- Then combo fires (e.g., T)
- Result: "Space T" instead of just "T"

**The Solution:**

With "Activate on release" enabled:
- Press modifier -> nothing fires yet, just tracks modifier state
- Press combo button while holding -> combo fires
- Release modifier -> if no combo was used, base action fires as tap

This gives you reliable combo detection without accidental base action triggers.

### Auto-Enable for Modifier Buttons

When you add a combo to a button (making it a modifier), the **"Activate on release" checkbox is automatically enabled**. This is the recommended behavior for most users.

**Why auto-enable?**
- Modifier buttons benefit most from on-release behavior
- Prevents the "base action + combo" double-fire problem
- You can still disable it if you prefer immediate behavior

**Auto-enable rules:**
- Adding first combo -> checkbox auto-enables
- User unchecks manually -> choice is remembered, won't auto-enable again
- Removing all combos -> checkbox stays as-is (you may want on-release for other reasons)

### Manually Configuring Activate on Release

**To enable/disable:**

1. **Select the button** in the Controls Configuration table
2. Find the **"Activate on release"** checkbox in the Control Editor
3. **Check or uncheck** the box
4. Click **"Apply"**, then **"Save"**

**When to manually enable (non-modifier buttons):**
- Buttons with double-press where you want consistent tap behavior
- Any button where you prefer release-triggered actions

**When to manually disable (modifier buttons):**
- You need the base action to fire immediately (e.g., holding Ctrl for click-drag)
- You're comfortable with the timing and don't experience double-fire issues

### How It Works with Double-Press

"Activate on release" uses **immediate fire** - the base action fires instantly on release:

**Single press:**
1. Press button -> nothing fires (deferred)
2. Release button -> single-press action fires **immediately** as tap

**Double press (dirty input):**
1. Press button -> nothing fires
2. Release button -> single-press action fires immediately as tap
3. Press button again (within timeout) -> double-press action fires as tap

**With combos:**
1. Hold modifier (with on-release) -> nothing fires
2. Press combo button -> combo fires
3. Release modifier -> no base action (combo was used, stays clean!)

### Example: Reliable Modifier Setup

**Scenario:** Short button mapped to Space, with combo Short+Tall=T

**Without Activate on Release:**
- Press Short -> Space fires immediately
- Press Tall while holding Short -> T fires
- Result: "Space T" (unwanted Space)

**With Activate on Release:**
- Press Short -> nothing fires (modifier tracked)
- Press Tall while holding Short -> T fires
- Release Short -> nothing fires (combo was used)
- Result: Just "T" (correct!)

**If you just tap Short:**
- Press Short -> nothing fires
- Release Short -> Space fires as tap
- Result: Just "Space" (correct!)

### Configuration in Profile Files

The setting is stored in your profile file:

```ini
[mappings]
short = KEY_SPACE
short.on_release = true
```

If you explicitly disable on-release for a modifier, this is also tracked:

```ini
short.on_release_disabled = true
```

This prevents auto-enable from overriding your choice when you edit combos later.

### Tips for Activate on Release

**1. Let it auto-enable for modifiers**
- The default auto-enable behavior works well for most users
- Only disable if you have a specific reason

**2. Use for buttons with both combos and double-press**
- Ensures consistent tap behavior for single-press
- Double-press detection works correctly

**3. Consider latency trade-offs**
- On-release adds a tiny delay (action fires on release, not press)
- For most uses, this is imperceptible
- If you need instant response (e.g., gaming), you may prefer off

**4. Test your workflow**
- After enabling, test your common button sequences
- Verify combos fire cleanly without base action interference

### Understanding Immediate Fire vs Activate on Release

The driver offers two modes for button behavior:

**Immediate Fire (Default):**
- Base action fires instantly on press - zero latency
- Hold behavior works (key stays down while held)
- Double-press: quick base tap, then double-press action
- Best for: pan, zoom, modifiers where instant response matters

**Activate on Release:**
- Base action deferred until release (fires as tap immediately)
- Clean combos (no base action before combo)
- Dirty double-press (base fires on release, then double-press on second press)
- Best for: tool switching, buttons with many combos

| Feature | Immediate Fire (Default) | Activate on Release |
|---------|-------------------------|---------------------|
| Base action timing | Instant on press | Instant on release (as tap) |
| Hold behavior | Works | Broken (fires as tap) |
| Double-press | Quick base tap first | Quick base tap on release first |
| Combos | Base may fire briefly | Clean (no base first) |

**Choose based on button function:**

| Button Function | Recommended Mode |
|-----------------|------------------|
| Pan canvas (Space) | Immediate Fire (default) |
| Zoom (Ctrl) | Immediate Fire (default) |
| Tool switching | Activate on Release |
| Many combos | Activate on Release |

### Troubleshooting Activate on Release

**Problem:** Base action never fires

**Solutions:**
1. Make sure you're releasing the button (action fires on release)
2. Check that a combo isn't being triggered accidentally
3. Verify the base action is configured (not empty)

**Problem:** Combo fires base action AND combo

**Solutions:**
1. Enable "Activate on release" for the modifier button
2. This is the exact problem on-release is designed to solve

**Problem:** Double-press doesn't work with on-release modifier

**Solutions:**
1. This should work automatically - both single and double-press fire on release
2. Check that double-press action is configured
3. Try adjusting the double-press timeout in Profile Settings

**Problem:** Checkbox keeps getting checked when I don't want it

**Solutions:**
1. Uncheck the box and save - your preference is remembered
2. The `on_release_disabled` flag prevents future auto-enable
3. This persists even if you edit combos later

---

## Configuring Haptic Feedback

### What is Haptic Feedback?

The TourBox Elite and Elite Plus have built-in haptic motors that provide vibration feedback when you rotate the knob, scroll wheel, or dial. This tactile feedback helps you feel each "click" or detent as you rotate, making it easier to make precise adjustments without looking at the screen.

> **Note:** Haptic feedback is only available on the TourBox Elite and Elite Plus. The TourBox Lite and Neo do not have haptic motors.

### Haptic Settings Overview

Haptic feedback has two configurable parameters:

**Strength** - Controls the intensity of the vibration:
- **Off** - No vibration feedback
- **Weak** - Subtle vibration, good for quiet environments
- **Strong** - More pronounced vibration, easier to feel

**Speed** - Controls how spaced out the detents feel when rotating:
- **Fast (more detents)** - More clicks per rotation, finer control
- **Medium** - Balanced spacing
- **Slow (fewer detents)** - Fewer clicks per rotation, coarser control

### Setting Profile-Wide Haptic Feedback

Each profile can have its own haptic settings. This is useful if you want different feedback for different applications (e.g., strong feedback for photo editing, off for video calls).

**To set haptic feedback for a profile:**

1. **Select the profile** in the Profiles list
2. Click the **"settings"** (settings) button to open Profile Settings
3. Find the **"Haptic Feedback"** section
4. Select your preferred **Strength** from the dropdown
5. Select your preferred **Speed** from the dropdown
6. Click **"Apply"**
7. Click **"Save"** (Ctrl+S) to write changes to config

When set at the profile level, the haptic settings apply to all three rotary controls (knob, scroll wheel, dial) in that profile as the default.

### Setting Per-Dial Haptic Feedback

For more granular control, you can set different haptic strength and speed for each individual dial. This is configured when editing a rotary control.

**To set haptic for a specific dial:**

1. **Select a rotary control** in the Controls Configuration table
   - Choose one of: `Scroll Up`, `Scroll Down`, `Knob Clockwise`, `Knob Counter-CW`, `Dial Clockwise`, or `Dial Counter-CW`
2. In the Control Editor, you'll see a **"Haptic Feedback"** section with two dropdowns side-by-side:
   - **Strength:** dropdown on the left
   - **Speed:** dropdown on the right
3. For each setting, select your preference:
   - **Use Profile Default** - Uses the profile's global setting
   - Or choose a specific value to override the profile default
4. Click **"Apply"**
5. Click **"Save"** (Ctrl+S)

**Example use cases:**
- **Scroll wheel for zooming:** Strong strength + Fast speed for precise zoom control
- **Dial for timeline scrubbing:** Off or Weak strength to avoid distraction during video editing
- **Knob for brush size:** Strong strength + Slow speed for deliberate size changes

### Haptic for Modifier Combinations

When you create a modifier combination that uses a rotary control (e.g., `Side + Knob Clockwise`), you can also set custom haptic strength and speed for that specific combination.

**To set haptic for a modifier+rotary combination:**

1. **Select the modifier button** (e.g., "side")
2. In the **Modifier Combinations** table, click **"Add Combination"** or edit an existing one
3. **Select a rotary control** as the target (e.g., `Knob Clockwise`)
4. The **"Haptic Feedback"** section appears in the dialog with:
   - **Strength:** dropdown
   - **Speed:** dropdown
5. Select your preferred settings for each
6. Click **"OK"**, then **"Apply"**, then **"Save"**

This allows you to have different haptic feedback depending on whether you're using the dial alone or with a modifier button held. For example:
- `Knob Clockwise` alone: Strong + Fast (for scrolling)
- `Side + Knob Clockwise`: Weak + Slow (for fine brush adjustments)

### Haptic Configuration Hierarchy

Haptic settings (both strength and speed) are applied in this priority order (highest to lowest):

1. **Per-combo setting** - Modifier + rotary combination (e.g., `Side + Knob Clockwise`)
2. **Per-dial setting** - Individual dial override (e.g., just `Knob`)
3. **Profile global setting** - Profile-wide haptic setting
4. **Default** - Off for strength, Fast for speed (if nothing is configured)

### Tips for Haptic Configuration

**1. Start with global settings**
- Set profile-wide strength and speed first
- Only add per-dial overrides if you need different behavior

**2. Consider your environment**
- Use "Weak" strength in quiet offices or during video calls
- Use "Strong" strength when you need precise tactile feedback

**3. Match haptic to function**
- **Coarse adjustments** (scrolling, zooming): Strong + Fast
- **Fine adjustments** (brush size, opacity): Weak + Slow or Medium
- **Timeline scrubbing**: Off or Weak to avoid distraction

**4. Speed affects precision feel**
- **Fast:** More detents = more precise, incremental control
- **Slow:** Fewer detents = faster sweeping movements

**5. Test with your applications**
- Save and test your haptic settings in your actual workflow
- Adjust based on what feels natural for each use case

---

## Configuring Modifier Key Delay

### What Is Modifier Key Delay?

When the TourBox sends a key combination like Ctrl+Z, it sends the modifier key (Ctrl) and the main key (Z) at nearly the same time. Most applications handle this correctly, but some applications -- particularly **GIMP** -- can fail to recognize the combination because the modifier key hasn't been fully registered before the main key arrives.

**Modifier key delay** adds a small pause (in milliseconds) between sending the modifier keys (Ctrl, Shift, Alt, Super) and the remaining keys in a combination. This gives the application time to register the modifier before the main key arrives.

> **Mouse combos are handled automatically.** Bindings that mix a modifier with a mouse event -- e.g. `Alt+Scroll Wheel`, `Ctrl+Left Click` -- always get a small built-in delay so the compositor has time to register the modifier before the click or scroll. You do **not** need to enable Modifier Key Delay for these. The setting documented here is specifically for **keyboard-only** combos in stubborn applications like GIMP. If you set a value larger than the built-in floor, your value still wins for mouse combos too.

### When Do You Need It?

You likely need modifier key delay if:

- **Keyboard combinations don't work in specific applications** -- e.g., pressing a button mapped to Ctrl+Z does nothing in GIMP, but works fine in other apps
- **Only the main key registers** -- e.g., you get "z" instead of "Ctrl+Z"
- **Combinations work intermittently** -- sometimes the combo registers, sometimes it doesn't

**Common applications that may need it:**
- GIMP (image editor)
- Some Java-based applications (IntelliJ, Android Studio)
- Some older GTK applications

Most applications (Firefox, VS Code, terminal emulators, etc.) do **not** need this setting.

### Global vs Per-Profile Setting

Modifier key delay can be configured at two levels:

1. **Global setting** -- In `~/.config/tuxbox/config.conf` under the `[device]` section. Applies to all profiles unless overridden.
2. **Per-profile setting** -- In the profile settings dialog. Overrides the global setting for that specific profile.

**Priority chain:** Per-profile value > Global `[device]` value > 0 (disabled)

This means you can leave the global setting at 0 (disabled) and only enable the delay for profiles that need it -- for example, your GIMP profile can have a 30ms delay while all other profiles remain at zero latency.

### Setting the Global Modifier Key Delay

Edit `~/.config/tuxbox/config.conf`:

```ini
[device]
modifier_delay = 30
```

This sets a 30ms delay for all profiles (unless a profile overrides it). Set to `0` to disable.

### Setting Per-Profile Modifier Key Delay (GUI)

1. **Select the profile** in the Profiles list (e.g., your GIMP profile)
2. Click the **"settings"** (settings) button to open Profile Settings
3. Find the **"Modifier Key Delay"** section
4. **Check** the **"Override global setting"** checkbox
5. Set the delay value using the spin box (0-100ms)
6. Click **"Apply"**
7. Click **"Save"** (Ctrl+S) to write changes to config

**When the checkbox is unchecked:** The profile uses the global setting from `config.conf` (or 0 if none is set).

**When the checkbox is checked:** The profile uses the value you set, regardless of the global setting. Setting it to 0 with the checkbox checked explicitly disables the delay for that profile, even if the global setting is non-zero.

### Recommended Values

| Value | Description |
|-------|-------------|
| `0` | Disabled (default) -- no delay between modifier and main keys |
| `20` | Minimal delay -- fixes most applications with combo issues |
| `30` | Safe default for problematic applications |
| `50` | Conservative -- use if lower values don't work |
| `>50` | Rarely needed -- may feel sluggish |

**Start with 20-30ms** and increase only if combinations still aren't recognized.

### Example: GIMP Profile with Modifier Delay

A typical setup where only GIMP needs the delay:

1. **Global setting:** Leave at 0 (or don't set it) -- most apps don't need it
2. **GIMP profile:** Open profile settings, check "Override global setting", set to 30ms
3. Click **"Apply"**, then **"Save"** (Ctrl+S) to write changes to config
4. **Result:** When you switch to GIMP, key combos have a 30ms modifier delay. When you switch to any other app, there's zero delay.

### Configuration in Profile Files

The setting is stored in your profile file's `[profile]` section:

```ini
[profile]
name = Gimp
app_id = gimp
modifier_delay = 30
```

When omitted (not present in the file), the profile uses the global setting. This is the default for all profiles.

### Tips

**1. Only enable where needed**
- Most applications handle simultaneous key events correctly
- Adding unnecessary delay makes all key combos slightly slower
- Per-profile configuration lets you target only the apps that need it

**2. Test after changing**
- Save your profile and switch to the target application
- Test several key combinations to verify they work reliably
- If combos still fail, increase the delay by 10ms and test again

**3. The delay applies to all key combos in the profile**
- Every mapped action that combines modifier keys with other keys will have the delay
- Simple key actions (single keys without modifiers) are not affected

---

## Global Settings

**File → Global Settings** edits the settings that apply to the driver as a
whole, rather than to a single profile. These are stored in the `[device]`
section of `~/.config/tuxbox/config.conf`.

### Connection

Which transports the driver may use:

| Option | Behaviour |
|--------|-----------|
| **Automatic** (default) | Uses the cable when it is plugged in, otherwise falls back to Bluetooth. Switches to USB as soon as the cable appears. |
| **USB only** | The Bluetooth radio is never used. The driver waits for the cable if the TourBox isn't connected yet. |
| **Bluetooth only** | USB ports are never checked. |

Choose **USB only** if you always connect by cable. On a laptop this stops the
driver periodically scanning over Bluetooth for a device that is never there.

### USB

**Serial port** - leave empty unless your TourBox appears on a non-standard
port. The driver probes all `/dev/ttyACM*` devices regardless.

### Behaviour

- **Haptics** - send haptic settings even when a profile leaves them at their defaults
- **Modifier delay** - the global default for [Modifier Key Delay](#configuring-modifier-key-delay); individual profiles can override it
- **Window check** - how often the focused window is checked for automatic profile switching. Not used on KDE Plasma, which reports window changes as they happen

### Applying changes

None of these settings are re-read while the driver is running, so the GUI
offers to restart the driver after saving. Answer **Yes** for the change to
take effect.

Your existing comments in `config.conf` are preserved, and a timestamped
backup is written before each save.

---

## Tips & Tricks

### Restarting the Driver

Use **File -> Restart Driver** to restart the TuxBox driver service and reload all profiles in the GUI.

**When to use Restart Driver:**

- **Switching connection types** - If you switch your TourBox from Bluetooth to USB (or vice versa) without rebooting or logging out, use Restart Driver to reconnect
- **Driver becomes unresponsive** - If button presses stop working, a restart often fixes it
- **After external config changes** - If you edited profile files outside the GUI

**What happens when you restart:**
1. The systemd service is restarted
2. The driver reconnects to your TourBox (USB or Bluetooth)
3. All profiles are reloaded from disk
4. The GUI updates to show the current profile state

> **Tip:** This is much faster than logging out and back in when switching between USB and Bluetooth connections!

### Desktop Environment Shortcuts

When you map TourBox buttons to modifier keys (Alt, Ctrl, Super, Shift), those key events may trigger your desktop environment's global shortcuts before reaching your application.

**How key events flow:**

1. You press TourBox buttons (e.g., ones mapped to Alt and Space)
2. TourBox sends button codes to the driver via USB or Bluetooth
3. The driver translates those codes to key events and sends them via uinput
4. Linux input subsystem receives the key events
5. **Your desktop environment gets first look** - it intercepts global shortcuts here
6. If not a global shortcut, the events reach the focused application

**Example:** If you map separate buttons to Alt and Space, pressing both together will trigger KDE's KRunner (Alt+Space) or GNOME's Activities search - the desktop intercepts these before your application ever sees them.

**Solutions for shortcut conflicts:**

1. **Disable the DE shortcut** - In your desktop's keyboard settings, disable or rebind the conflicting shortcut
2. **Use different keys** - Choose key combinations that don't conflict with your DE's defaults
3. **Check common conflicts:**
   - Alt+Space (KDE KRunner, window menu)
   - Alt+Tab (window switching)
   - Super key (application menu/overview)
   - Alt+F2 (command runner)
   - Ctrl+Alt+T (terminal)

> **Note:** This isn't a driver bug - it's how Linux input handling works. The driver correctly sends key events; your desktop environment simply processes global shortcuts before applications do.

### Keyboard Navigation

Speed up your workflow with keyboard shortcuts:

- **Ctrl+S** - Save changes and apply configuration
- **Arrow keys** - Navigate between controls in the list
- **Tab** - Move between UI elements

### Workflow Efficiency

**Quick iteration:**
1. Keep the GUI open during setup
2. Apply and Save changes
3. Switch to your application to test
4. Switch back to GUI -> tweak -> save -> test again
5. No need to close the GUI or restart anything

**Bulk editing:**
1. Configure one profile completely
2. Create new profile based on it
3. Change only what's different
4. Saves time vs. configuring from scratch

### Common Mapping Patterns

**Undo/Redo:**
- `short` -> Ctrl+Z (undo)
- `tall` -> Ctrl+Shift+Z (redo)

**Zoom:**
- `knob_cw` -> Ctrl+= (zoom in)
- `knob_ccw` -> Ctrl+- (zoom out)

**Scrolling:**
- `dial_cw` -> Scroll Up
- `dial_ccw` -> Scroll Down

**Modifiers:**
- `side` -> Super (start menu)
- `top` -> Shift
- `tall` -> Alt
- `short` -> Ctrl

**Navigation:**
- `dpad_up/down` -> Page Up/Page Down
- `dpad_left/right` -> Home/End

### Visual Feedback

- **Yellow highlight** on controller view shows selected control that has no modifiers or the modifier itself
- **Turquoise highlight** on controller view shows the control that is the base control (that has combination modifiers defined for it)
- **Orange ! icon** in profile name indicates conflicting window rules with another active profile
- **Asterisk (*)** in window title means unsaved changes
- **"(unmapped)"** in controls list means no action assigned
- **Status bar** shows what's happening

---

## Checking for Updates

To check if a new version of TuxBox is available:

1. Open the GUI: `tuxbox-gui`
2. Click **Help -> Check for Updates**
3. The GUI will check GitHub for the latest version
4. If an update is available, follow the instructions in the dialog

**What happens:**
- The GUI fetches version information from GitHub
- Compares it with your installed version
- Shows a dialog with the result

**If an update is available:**
- The dialog shows update instructions with the correct path to your installation
- Click "View on GitHub" to see the release notes
- Run the commands shown to update

**Note:** This requires an internet connection. The check only reads version information from GitHub and does not send any data.

---

## Troubleshooting

### GUI Won't Launch

**Problem:** Error when running `tuxbox-gui`

**Solutions:**
1. Check that launcher script exists:
   ```bash
   ls -la /usr/local/bin/tuxbox-gui
   ```
2. If missing, re-run installer or create manually:
   ```bash
   cd /path/to/tuxbox
   ./install.sh
   ```
3. If launcher exists but still fails, check GUI dependencies:
   ```bash
   /path/to/tuxbox/venv/bin/pip install -r tuxbox/gui/requirements.txt
   ```
4. Verify Qt installation:
   ```bash
   /path/to/tuxbox/venv/bin/python -c "from PySide6 import QtWidgets; print('OK')"
   ```

### Driver Won't Stop/Start

**Problem:** GUI shows error when stopping/starting driver

**Solutions:**
1. Check if driver is installed as systemd service:
   ```bash
   systemctl --user status tuxbox
   ```
2. If not installed, see main README.md installation section
3. Try manual stop/start:
   ```bash
   systemctl --user stop tuxbox
   systemctl --user start tuxbox
   ```

### No Profiles Found

**Problem:** "No profiles found in configuration"

**Solutions:**
1. Check profiles directory exists:
   ```bash
   ls -la ~/.config/tuxbox/profiles/
   ```
2. If missing, run `./install_config.sh` to create default config
3. Check file permissions (should be readable)
4. Verify at least `default.profile` exists in the profiles directory

### Changes Not Saving

**Problem:** Click Save but changes don't persist

**Solutions:**
1. Check for error dialogs (file permissions, disk space)
2. Verify profiles directory is writable:
   ```bash
   ls -la ~/.config/tuxbox/profiles/
   ```
3. Check disk space:
   ```bash
   df -h ~
   ```
4. Look for backup files (confirms writes are working):
   ```bash
   ls -la ~/.config/tuxbox/profiles/*.backup.*
   ```

### Button Presses Don't Work in When Testing

**Problem:** Physical button presses do nothing during Test

**Solutions:**
1. Check driver status:
   ```bash
   systemctl --user status tuxbox
   ```
2. Check driver logs for errors:
   ```bash
   journalctl --user -u tuxbox -n 50
   ```
3. Verify TourBox is powered on and in range
4. Try reconnecting Bluetooth:
   - Stop test
   - Turn TourBox off and on
   - Start test again

### Profile Switching Not Working

**Problem:** Profile doesn't activate when switching windows

**Solutions:**
1. Check window matching rules are correct:
   - Use "Capture Active Window" feature
   - Verify app_id or window_class matches
2. Check which compositor you're using:
   ```bash
   echo $XDG_SESSION_TYPE  # Should be "wayland"
   echo $XDG_CURRENT_DESKTOP  # Shows your desktop
   ```
3. For GNOME: Install the Focused Window D-Bus extension
4. For KDE: Install `kdotool`
5. Check driver logs to see profile switching:
   ```bash
   journalctl --user -u tuxbox -f
   ```
   Should show: "Switched to profile: [name]"

### Window Capture Not Working

**Problem:** "Capture Active Window" doesn't detect window

**Solutions:**
1. Make sure you're on **Wayland** (not X11):
   ```bash
   echo $XDG_SESSION_TYPE
   ```
2. Install compositor-specific tools:
   - **GNOME:** Focused Window D-Bus Extension
   - **KDE:** kdotool package
   - **Sway/Hyprland:** Built-in IPC (should work)
3. Click the target window during the 5-second countdown
4. If detection fails, manually enter window class/app_id

### GUI Freezes or Crashes

**Problem:** GUI becomes unresponsive

**Solutions:**
1. Check system resources (RAM, CPU):
   ```bash
   top
   ```
2. Kill and restart GUI:
   ```bash
   pkill -f "tuxbox.gui"
   tuxbox-gui
   ```
3. Check for Qt/Python errors in terminal output
4. Restart driver if it was left in stopped state:
   ```bash
   systemctl --user start tuxbox
   ```

### Config File Corrupted

**Problem:** Can't load config, syntax errors

**Solutions:**
1. Restore a specific profile from automatic backup:
   ```bash
   cd ~/.config/tuxbox/profiles/
   ls -la *.backup.*
   cp default.profile.backup.YYYYMMDD_HHMMSS default.profile
   ```
2. Or reset to defaults (removes all profiles):
   ```bash
   rm -rf ~/.config/tuxbox/profiles ~/.config/tuxbox/config.conf
   ./install_config.sh
   ```
   WARNING: Loses all customizations!

### Getting Help

If you encounter issues not covered here:

1. **Check logs:**
   ```bash
   journalctl --user -u tuxbox -n 100
   ```

2. **Enable verbose logging in GUI:**
   Edit `tuxbox/gui/main_window.py` and change:
   ```python
   logging.basicConfig(level=logging.DEBUG)
   ```

3. **Report issues:**
   - GitHub: https://github.com/AndyCappDev/tuxbox/issues
   - Include: OS, desktop environment, error messages, logs

---

## Appendix: Configuration File Format

The GUI reads and writes profiles to individual files in `~/.config/tuxbox/profiles/`.

**File Structure:**
```
~/.config/tuxbox/
├── config.conf              # Device settings (MAC address, USB port)
└── profiles/
    ├── default.profile      # Default profile
    ├── vscode.profile       # Application-specific profile
    └── ...
```

**Example Profile (`default.profile`):**
```ini
[profile]
name = default

[mappings]
side = KEY_LEFTMETA
top = KEY_LEFTSHIFT
tall = KEY_LEFTALT
short = KEY_LEFTCTRL
scroll_up = REL_WHEEL:1
scroll_down = REL_WHEEL:-1
knob_cw = KEY_LEFTCTRL+KEY_EQUAL
knob_ccw = KEY_LEFTCTRL+KEY_MINUS
# ... etc

[profile:firefox]
app_id = firefox-esr
window_class = firefox-esr
side = KEY_LEFTCTRL+KEY_T
tall = KEY_LEFTCTRL+KEY_W
# ... etc
```

**Profile sections:**
- `[profile:name]` - Section header
- `window_class`, `app_id` - Optional matching rules
- Control mappings - One line per control

**Action formats:**
- Keyboard: `KEY_LEFTCTRL+KEY_C` (modifiers+key)
- Mouse scroll: `REL_WHEEL:1` (scroll up), `REL_WHEEL:-1` (scroll down)
- Mouse buttons: `BTN_LEFT`, `BTN_RIGHT`, `BTN_MIDDLE`
- Unmapped: Omit the line or set to empty

The GUI preserves comments and formatting when saving!

---

## Quick Reference Card

### Keyboard Shortcuts
- **Ctrl+S** - Save changes and apply configuration
- **Arrow keys** - Navigate controls

### Workflow
1. Select profile
2. Click control
3. Configure action
4. Apply
5. Save (Ctrl+S) - applies automatically
6. Switch to app and test

### Action Types
- **Keyboard** - Key combos (Ctrl+C, Alt+F4, etc.)
- **Mouse** - Scroll up/down/left/right, left/right/middle click
- **None** - Disable control

### Profile Management
- **"+"** - Create new profile
- **"settings"** - Edit profile settings
- **"-"** - Delete profile
- **Active checkbox** - Enable/disable profile for window matching
- **Import** - Import a profile from file
- **Export** - Export selected profile to file
- **Capture** (in settings) - Auto-detect window info
- **Orange !** - Profile conflicts with another active profile

### Importing and Exporting Profiles

**Exporting a Profile:**
1. Select the profile you want to export
2. Click **Export** button or use **File > Export Profile...**
3. Choose a location and filename
4. Share the `.profile` file with others

**Importing a Profile:**
1. Click **Import** button or use **File > Import Profile...**
2. Select a `.profile` file
3. If a profile with the same name exists, you can:
   - **Replace** the existing profile
   - **Rename** the imported profile
4. The imported profile appears in your list

### Testing
1. Click "Save"
2. Switch to your app
3. Try physical buttons
4. Switch back to GUI to adjust
5. Repeat as needed

---

**Enjoy your TourBox with the power of a visual configuration tool!**

For technical details, see:
- [CONFIG_GUIDE.md](CONFIG_GUIDE.md) - Manual config editing
- [DEVELOPMENT.md](DEVELOPMENT.md) - Architecture and code
