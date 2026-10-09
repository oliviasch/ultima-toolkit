"""
steamstats is five modules:
- steamapi.py  everything that talks to Steam
- store.py     on-disk profile cache
- profile.py   API responses to profile model
- render.py    profile model to HTML
- server.py    routing and the request handler
"""

from server import main

if __name__ == "__main__":
    main()
