# build-settings.py

# Define the window size and background image
window_rect = ((100, 100), (640, 480))
background = 'dmg-background.png'

# Define the icon locations
icon_locations = {
    'Streamdeck Commander.app': (180, 240),
    'Applications': (460, 240)
}

# Define the list of files to include
files = [ 'dist/Streamdeck Commander.app' ]

# Define the symlinks to create
symlinks = { 'Applications': '/Applications' }
